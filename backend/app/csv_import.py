"""
Импорт заявок из файлов.

Район (жёсткий критерий отбора инженера) берётся из ИМЕНИ ФАЙЛА/офиса
(например "Восток", "Юго-Восток", "Югоцентр"), а не из колонки заявки —
конкретные районы внутри файла (Кузьминки, Таганский и т.п., если такая
колонка есть в CSV) игнорируются.

Срочность заявки — исключительно ручной флаг, который выставляет
оператор; автоматической привязки срочности к какому-либо типу заявки
(в т.ч. к типу «Авария») больше нет.

Поддерживаются два формата:

1. CSV в том виде, в котором приходит реальная выгрузка (пример —
   присланные файлы "Восток_Синтетические_данные.csv"):
   - кодировка cp1251, разделитель ';'
   - колонки: Заявка; Тип заявки BK; Тип заявки HD; Начало; Окончание;
     [Район — игнорируется]; Адрес; [Подключение: FMC / FTTB / пусто — для FMC и FTTB нужно
     дополнительное оборудование бригады, пусто = без него]; [Гигабитное подключение];
     [Требуемые инструменты — необязательная колонка, список оборудования
     через запятую внутри ячейки; если колонки нет — оборудование не требуется]
   - последняя содержательная строка файла — не заявка, а адрес офиса:
     "Адрес Офиса;<адрес>;;;;;;;" (регистр слов не важен — "Адрес офиса",
     "адрес Офиса" и т.п. тоже распознаются)
   - могут быть пустые "мусорные" строки перед этой строкой — пропускаются.

2. JSON-список объектов вида:
   {
     "office_name": "...", "office_address": "...",
     "requests": [
        {"id": "...", "address": "...",
         "window_start": "2026-08-17T10:00:00", "window_end": "...",
         "skill": "local|connect|emergency", "reason": "...",
         "duration_min": 60, "urgent": false,
         "required_equipment": ["..."],   (необязательно)
         "required_transport": "car|walk|bike|transit"|null}
        , ...
     ]
   }
   (район у заявки в JSON, если передан, тоже игнорируется — берётся из
   office_name/имени файла, как и для CSV)

Обе ветки возвращают набор "сырых" заявок (без координат — геокодирование
делается отдельно, асинхронно) плюс адрес офиса файла и список
СТРУКТУРИРОВАННЫХ предупреждений импорта (файл, номер строки, тип
проблемы, текст) — см. ImportWarning.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from .models import Request, Skill, Transport


def split_list_cell(value: str) -> set[str]:
    """Ячейка со списком через запятую -> множество строк. Сравнение
    оборудования потом идёт ТОЧНО (посимвольно), без исправления опечаток —
    осознанный выбор: молчаливое «угадывание» могло бы отправить бригаду
    на заявку без нужного оборудования. Убираем только края и лишние
    пробелы внутри."""
    items = (" ".join(part.split()) for part in value.replace("\n", ",").split(","))
    return {i for i in items if i}

# Тип заявки BK -> навык. Сравнение регистронезависимое и не чувствительно
# к лишним пробелам (см. _normalize_bk_type) — подтверждено оператором.
_BK_TYPE_TO_SKILL = {
    "локальная заявка": Skill.LOCAL,
    "подключение": Skill.CONNECT,
    "дозаказ": Skill.CONNECT,
    "глобальная проблема": Skill.EMERGENCY,
}

_DATE_FORMAT = "%d.%m.%Y %H:%M"


def district_from_filename(source_name: str) -> str:
    """Район = имя файла без расширения; если в имени есть «_», район — то,
    что стоит до первого «_» (например «Восток_Синтетические_данные.csv» ->
    «Восток»), чтобы служебные хвосты в имени выгрузки не становились
    частью названия района."""
    base = source_name.rsplit(".", 1)[0].strip()
    head = base.split("_", 1)[0].strip()
    return head or base


def _normalize_bk_type(value: str) -> str:
    """Регистр и лишние пробелы у 'Тип заявки BK' в реальных выгрузках
    плавают ('Подключение' / 'подключение' / 'ПОДКЛЮЧЕНИЕ ') — приводим
    к единому виду перед сравнением со справочником."""
    return " ".join(value.strip().lower().split())


@dataclass
class ImportWarning:
    file: str
    type: str                  # машиночитаемый код проблемы, см. WARNING_TYPE_LABELS на фронте
    message: str                # готовый текст на русском
    line: int | None = None     # номер строки в CSV (с учётом заголовка), либо позиция в JSON


@dataclass
class ImportResult:
    office_name: str
    office_address: str | None
    requests: list[Request]
    warnings: list[ImportWarning]


def _parse_dt(value: str) -> datetime:
    value = value.strip()
    return datetime.strptime(value, _DATE_FORMAT)


def import_csv(file_bytes: bytes, source_name: str) -> ImportResult:
    warnings: list[ImportWarning] = []
    requests: list[Request] = []
    office_address: str | None = None

    # Район заявки = имя файла (макро-регион: Восток/Юго-Восток/Югоцентр
    # и т.п.); колонка "Район" в CSV (московские районы вроде "Кузьминки")
    # игнорируется по решению оператора.
    file_district = district_from_filename(source_name)

    # Пробуем cp1251 (родная кодировка выгрузки), затем utf-8 на случай,
    # если файл пересохранили.
    text = None
    for enc in ("cp1251", "utf-8-sig", "utf-8"):
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"Не удалось определить кодировку файла {source_name}")

    reader = csv.reader(io.StringIO(text), delimiter=";")
    rows = list(reader)
    if not rows:
        raise ValueError(f"Файл {source_name} пуст")

    header = [h.strip() for h in rows[0]]
    try:
        idx_id = header.index("Заявка")
        idx_bk = header.index("Тип заявки BK")
        idx_hd = header.index("Тип заявки HD")
        idx_start = header.index("Начало")
        idx_end = header.index("Окончание")
        idx_address = header.index("Адрес")
    except ValueError as exc:
        raise ValueError(f"Файл {source_name}: не найдена ожидаемая колонка ({exc})")
    idx_conn = header.index("Подключение") if "Подключение" in header else None
    idx_tools = header.index("Требуемые инструменты") if "Требуемые инструменты" in header else None

    for row_num, row in enumerate(rows[1:], start=2):
        if not row or all(not c.strip() for c in row):
            continue  # пустая техническая строка

        first_cell = row[0].strip()
        # Регистр в файлах на практике плавает: "Адрес Офиса" / "Адрес офиса" —
        # сравниваем без учёта регистра, чтобы не терять офис из-за этого.
        if first_cell.lower() == "адрес офиса":
            office_address = row[1].strip() if len(row) > 1 else None
            continue

        if len(row) <= max(idx_id, idx_bk, idx_hd, idx_start, idx_end, idx_address):
            warnings.append(ImportWarning(
                file=source_name, line=row_num, type="too_few_columns",
                message="недостаточно колонок в строке, строка пропущена",
            ))
            continue

        req_id_raw = row[idx_id].strip()
        if not req_id_raw:
            continue

        bk_type = row[idx_bk].strip()
        skill = _BK_TYPE_TO_SKILL.get(_normalize_bk_type(bk_type))
        if skill is None:
            warnings.append(ImportWarning(
                file=source_name, line=row_num, type="unknown_bk_type",
                message=f"неизвестный 'Тип заявки BK' = '{bk_type}' (заявка {req_id_raw}), строка пропущена",
            ))
            continue

        try:
            window_start = _parse_dt(row[idx_start])
            window_end = _parse_dt(row[idx_end])
        except ValueError:
            warnings.append(ImportWarning(
                file=source_name, line=row_num, type="invalid_date",
                message=f"некорректный формат даты (заявка {req_id_raw}), строка пропущена",
            ))
            continue

        address = row[idx_address].strip()
        if not address:
            warnings.append(ImportWarning(
                file=source_name, line=row_num, type="empty_address",
                message=f"пустой адрес (заявка {req_id_raw}), строка пропущена",
            ))
            continue

        reason = row[idx_hd].strip()
        required_equipment = (
            split_list_cell(row[idx_tools]) if idx_tools is not None and len(row) > idx_tools else set()
        )

        # «Подключение» = FMC / FTTB -> нужно дополнительное оборудование;
        # пусто (или иное значение) -> «без дополнительного оборудования»
        connection_type = None
        if idx_conn is not None and len(row) > idx_conn:
            value = row[idx_conn].strip().upper()
            connection_type = value if value in ("FMC", "FTTB") else None

        internal_id = f"{source_name}:{req_id_raw}"
        requests.append(
            Request(
                id=internal_id,
                address=address,
                district=file_district,
                window_start=window_start,
                window_end=window_end,
                skill=skill,
                reason=reason,
                duration_min=_default_duration(skill),
                urgent=False,
                required_transport=None,
                required_equipment=required_equipment,
                connection_type=connection_type,
                source_file=source_name,
            )
        )

    if office_address is None:
        warnings.append(ImportWarning(
            file=source_name, line=None, type="no_office_address",
            message="строка 'Адрес Офиса' не найдена — офис для этого файла придётся добавить вручную",
        ))

    return ImportResult(
        office_name=file_district,
        office_address=office_address,
        requests=requests,
        warnings=warnings,
    )


def _default_duration(skill: Skill) -> int:
    from .config import DEFAULT_DURATION_MIN
    return DEFAULT_DURATION_MIN[skill.value]


def import_json(file_bytes: bytes, source_name: str) -> ImportResult:
    warnings: list[ImportWarning] = []
    requests: list[Request] = []

    data = json.loads(file_bytes.decode("utf-8"))
    office_name = data.get("office_name") or district_from_filename(source_name)
    office_address = data.get("office_address")
    # Тот же принцип, что и для CSV: район = имя файла/офиса, а не то, что
    # может быть указано у отдельной заявки в JSON.
    file_district = office_name

    for position, item in enumerate(data.get("requests", []), start=1):
        try:
            skill = Skill(item["skill"])
        except (KeyError, ValueError):
            warnings.append(ImportWarning(
                file=source_name, line=position, type="invalid_skill",
                message=f"некорректный skill в заявке {item.get('id')}, запись пропущена",
            ))
            continue

        req_transport = None
        if item.get("required_transport"):
            try:
                from .models import Transport
                req_transport = Transport(item["required_transport"])
            except ValueError:
                warnings.append(ImportWarning(
                    file=source_name, line=position, type="invalid_transport",
                    message=f"некорректный required_transport в заявке {item.get('id')}, требование проигнорировано",
                ))

        try:
            window_start = datetime.fromisoformat(item["window_start"])
            window_end = datetime.fromisoformat(item["window_end"])
        except (KeyError, ValueError):
            warnings.append(ImportWarning(
                file=source_name, line=position, type="invalid_date",
                message=f"некорректные даты в заявке {item.get('id')}, запись пропущена",
            ))
            continue

        raw_id = str(item.get("id") or uuid.uuid4())
        requests.append(
            Request(
                id=f"{source_name}:{raw_id}",
                address=item["address"],
                district=file_district,
                window_start=window_start,
                window_end=window_end,
                skill=skill,
                reason=item.get("reason", ""),
                duration_min=int(item.get("duration_min", _default_duration(skill))),
                urgent=bool(item.get("urgent", False)),
                required_transport=req_transport,
                required_equipment=_json_equipment(item.get("required_equipment")),
                connection_type=(
                    str(item.get("connection_type")).strip().upper()
                    if str(item.get("connection_type") or "").strip().upper() in ("FMC", "FTTB") else None
                ),
                source_file=source_name,
            )
        )

    return ImportResult(
        office_name=office_name,
        office_address=office_address,
        requests=requests,
        warnings=warnings,
    )


def _json_equipment(value) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        return split_list_cell(value)
    return {" ".join(str(v).split()) for v in value if str(v).strip()}


# ------------------------------------------------------------ бригады

# Компетенции в файле бригад -> навык: новые названия («Ремонт» /
# «Новое подключение» / «Авария»), прежние названия, внутренние коды и
# «Тип заявки BK» — без учёта регистра/пробелов. Остальное — предупреждение.
_COMPETENCE_TO_SKILL = {
    "ремонт": Skill.LOCAL,
    "локальные работы": Skill.LOCAL,
    "локальная заявка": Skill.LOCAL,
    "local": Skill.LOCAL,
    "новое подключение": Skill.CONNECT,
    "подключение": Skill.CONNECT,
    "дозаказ": Skill.CONNECT,
    "работы на подключение и дозаказы": Skill.CONNECT,
    "connect": Skill.CONNECT,
    "авария": Skill.EMERGENCY,
    "аварийные работы": Skill.EMERGENCY,
    "глобальная проблема": Skill.EMERGENCY,
    "emergency": Skill.EMERGENCY,
}


# Транспорт в файле бригад -> Transport (названия как в интерфейсе + коды)
_TRANSPORT_NAMES = {
    "автомобиль": Transport.CAR, "car": Transport.CAR,
    "пешеход": Transport.WALK, "walk": Transport.WALK,
    "велосипед": Transport.BIKE, "bike": Transport.BIKE,
    "общественный транспорт": Transport.TRANSIT, "transit": Transport.TRANSIT,
}


@dataclass
class ParsedEngineer:
    name: str
    skills: set[Skill]
    equipment: set[str]
    transport: Transport | None
    line: int


@dataclass
class EngineersImportResult:
    engineers: list[ParsedEngineer]
    warnings: list[ImportWarning]
    district: str | None = None      # район из файла (блок «Район» под таблицей), если есть


def import_engineers_csv(file_bytes: bytes, source_name: str) -> EngineersImportResult:
    """Файл бригад: UTF-8 (с BOM или без; на случай пересохранения — cp1251),
    разделитель ';'. Колонки: «Бригада; Компетенции; Оборудование; Транспорт»
    (порядок и пустые колонки между ними не важны), в «Компетенции» и
    «Оборудование» — списки через запятую внутри ячейки, «Транспорт» —
    Автомобиль / Пешеход / Велосипед / Общественный транспорт.

    Район — в самом файле: после таблицы строка «Район», а в следующей строке
    (или во втором столбце той же строки) — название района. Смена в файле
    не задаётся — её выставляет оператор (см. store.import_engineers_csv)."""
    text = None
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"Не удалось определить кодировку файла {source_name}")

    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    if not rows:
        raise ValueError(f"Файл {source_name} пуст")

    header = [h.strip() for h in rows[0]]
    try:
        idx_name = header.index("Бригада")
        idx_comp = header.index("Компетенции")
        idx_equip = header.index("Оборудование")
    except ValueError as exc:
        raise ValueError(f"Файл {source_name}: не найдена ожидаемая колонка ({exc})")
    idx_transport = header.index("Транспорт") if "Транспорт" in header else None

    warnings: list[ImportWarning] = []
    engineers: list[ParsedEngineer] = []
    seen: set[str] = set()
    district: str | None = None
    expect_district = False

    for row_num, row in enumerate(rows[1:], start=2):
        if not row or all(not c.strip() for c in row):
            continue

        first = row[0].strip()
        if expect_district:
            # строка сразу после «Район» — само название района
            district = first or None
            expect_district = False
            continue
        if first.lower() == "район":
            second = row[1].strip() if len(row) > 1 else ""
            if second:
                district = second
            else:
                expect_district = True
            continue

        if len(row) <= max(idx_name, idx_comp, idx_equip):
            warnings.append(ImportWarning(
                file=source_name, line=row_num, type="too_few_columns",
                message="недостаточно колонок в строке, строка пропущена",
            ))
            continue

        name = " ".join(row[idx_name].split())
        if not name:
            continue
        if name in seen:
            warnings.append(ImportWarning(
                file=source_name, line=row_num, type="duplicate_engineer",
                message=f"бригада «{name}» встречается в файле повторно, строка пропущена",
            ))
            continue

        skills: set[Skill] = set()
        for comp in split_list_cell(row[idx_comp]):
            skill = _COMPETENCE_TO_SKILL.get(comp.lower())
            if skill is None:
                warnings.append(ImportWarning(
                    file=source_name, line=row_num, type="unknown_competence",
                    message=f"неизвестная компетенция «{comp}» у бригады «{name}», пропущена",
                ))
            else:
                skills.add(skill)
        if not skills:
            warnings.append(ImportWarning(
                file=source_name, line=row_num, type="no_skills",
                message=f"у бригады «{name}» нет ни одной распознанной компетенции, строка пропущена",
            ))
            continue

        transport = None
        if idx_transport is not None and len(row) > idx_transport:
            raw = " ".join(row[idx_transport].split())
            if raw:
                transport = _TRANSPORT_NAMES.get(raw.lower())
                if transport is None:
                    warnings.append(ImportWarning(
                        file=source_name, line=row_num, type="unknown_transport",
                        message=f"неизвестный транспорт «{raw}» у бригады «{name}»",
                    ))

        seen.add(name)
        engineers.append(ParsedEngineer(
            name=name, skills=skills, equipment=split_list_cell(row[idx_equip]),
            transport=transport, line=row_num,
        ))

    return EngineersImportResult(engineers=engineers, warnings=warnings, district=district)
