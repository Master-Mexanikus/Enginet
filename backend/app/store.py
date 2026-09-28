"""
Единое состояние приложения в памяти процесса + операции над ним,
которые дальше вызывает FastAPI-слой (main.py).

Никакой БД сознательно нет: для хакатон-демо на 10-15 инженерах и до
100 заявках это ничем не хуже, а сильно проще. Состояние теряется при
перезапуске процесса — это ожидаемо.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from . import csv_import, planner
from .models import EQUIPMENT_TO_SKILL, EXTRA_EQUIPMENT, Engineer, Office, Plan, Request, RequestStatus, Skill, Transport

state = planner.PlannerState()
_last_plan: Plan | None = None


_simulation_time: datetime | None = None


def get_simulation_time() -> datetime | None:
    return _simulation_time


def set_simulation_time(value: datetime | None) -> datetime | None:
    global _simulation_time
    _simulation_time = value
    return _simulation_time


def get_last_plan() -> Plan | None:
    return _last_plan


def _set_last_plan(plan: Plan) -> Plan:
    global _last_plan
    _last_plan = plan
    return plan


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------- офисы

def update_office(office_id: str, name: str) -> Office:
    office = state.offices.get(office_id)
    if office is None:
        raise ValueError("Офис не найден")
    if name and name.strip():
        office.name = name.strip()
    return office


def list_offices() -> list[Office]:
    return list(state.offices.values())


def delete_office(office_id: str) -> None:
    in_use = [e for e in state.engineers.values() if e.office_id == office_id]
    if in_use:
        raise ValueError(
            f"Офис используется {len(in_use)} инженер(ами) — сначала измените их офис"
        )
    state.offices.pop(office_id, None)


def _find_office_and_district(district: str) -> tuple[Office, str] | None:
    """Офис и «канонический» район (в том написании, как он записан у заявок)
    — регистр не важен. Офис определяется автоматически по району."""
    normalized = district.strip().casefold()
    for office in state.offices.values():
        for d in office.districts:
            if d.casefold() == normalized:
                return office, d
    return None


def find_office_for_district(district: str) -> Office | None:
    found = _find_office_and_district(district)
    return found[0] if found else None


def _no_office_message(district: str) -> str:
    known = sorted({d for o in state.offices.values() for d in o.districts})
    hint = f" Сейчас есть районы: {', '.join(known)}." if known else " Пока не импортировано ни одного файла заявок."
    return (
        f"Нет офиса для района «{district.strip()}» — сначала импортируйте файл заявок "
        f"для этого района (район заявок берётся из имени файла: «Восток.csv» → «Восток»).{hint}"
    )


def _skills_from_equipment(equipment: set[str]) -> set[Skill]:
    return {EQUIPMENT_TO_SKILL[e] for e in equipment if e in EQUIPMENT_TO_SKILL}


# ------------------------------------------------------------ инженеры

def _clean_items(items) -> set[str]:
    return {" ".join(i.split()) for i in (items or []) if i and i.strip()}


def _clean_connection_type(value: str | None) -> str | None:
    """"FMC" / "FTTB" (регистр не важен) -> нормализованное значение;
    пусто/что-то иное -> None («без дополнительного оборудования»)."""
    normalized = (value or "").strip().upper()
    return normalized if normalized in EXTRA_EQUIPMENT else None


def add_engineer(
    name: str, skills: list[str], shift_start: datetime, shift_end: datetime,
    transport: str, district: str, equipment: list[str] | None = None,
) -> Engineer:
    if not district or not district.strip():
        raise ValueError("Не указан район инженера")
    found = _find_office_and_district(district)
    if found is None:
        raise ValueError(_no_office_message(district))
    office, district = found
    equipment_set = _clean_items(equipment)
    # тип заявок = оборудование: если навыки не переданы явно (форма их больше
    # не содержит), они выводятся из основного оборудования бригады
    skill_set = {Skill(s) for s in (skills or [])} or _skills_from_equipment(equipment_set)
    if not skill_set:
        raise ValueError(
            "Выберите оборудование бригады: «Оборудование для ремонта», «…для подключения» "
            "и/или «…для аварийных работ» — от него зависит, какие заявки она берёт"
        )
    engineer = Engineer(
        id=new_id("eng"),
        name=name,
        skills=skill_set,
        shift_start=shift_start,
        shift_end=shift_end,
        transport=Transport(transport),
        office_id=office.id,
        district=district.strip(),
        equipment=equipment_set,
    )
    state.engineers[engineer.id] = engineer
    state.routes.setdefault(engineer.id, [])
    return engineer


def update_engineer(engineer_id: str, **fields) -> Engineer:
    engineer = state.engineers[engineer_id]
    if "name" in fields and fields["name"] is not None:
        engineer.name = fields["name"]
    if "skills" in fields and fields["skills"] is not None:
        engineer.skills = {Skill(s) for s in fields["skills"]}
    if "shift_start" in fields and fields["shift_start"] is not None:
        engineer.shift_start = fields["shift_start"]
    if "shift_end" in fields and fields["shift_end"] is not None:
        engineer.shift_end = fields["shift_end"]
    if "transport" in fields and fields["transport"] is not None:
        engineer.transport = Transport(fields["transport"])
    if "equipment" in fields and fields["equipment"] is not None:
        engineer.equipment = _clean_items(fields["equipment"])
        if fields.get("skills") is None:
            derived = _skills_from_equipment(engineer.equipment)
            if not derived:
                raise ValueError(
                    "Выберите оборудование бригады: «Оборудование для ремонта», «…для подключения» "
                    "и/или «…для аварийных работ»"
                )
            engineer.skills = derived
    if "district" in fields and fields["district"] is not None and fields["district"].strip():
        found = _find_office_and_district(fields["district"])
        if found is None:
            raise ValueError(_no_office_message(fields["district"]))
        office, new_district = found
        engineer.district = new_district
        engineer.office_id = office.id   # офис всегда следует за районом автоматически
    return engineer


def list_engineers() -> list[Engineer]:
    return list(state.engineers.values())


def list_known_equipment() -> list[str]:
    """Всё оборудование, встречающееся у бригад и в заявках — подсказки для форм."""
    items: set[str] = set(EXTRA_EQUIPMENT.values()) | set(EQUIPMENT_TO_SKILL)
    for e in state.engineers.values():
        items |= e.equipment
    for r in state.requests.values():
        items |= r.required_equipment
    return sorted(items)


def list_known_districts() -> list[str]:
    """Список районов, встретившихся в импортированных/добавленных заявках —
    используется фронтендом для выбора района при создании профиля инженера."""
    districts = {r.district.strip() for r in state.requests.values() if r.district and r.district.strip()}
    return sorted(districts)


def delete_engineer(engineer_id: str) -> None:
    route = state.routes.get(engineer_id, [])
    if route:
        raise ValueError(
            "У инженера есть назначенные заявки — сначала переведите его в статус "
            "«недоступен» (это освободит заявки), затем удаляйте"
        )
    state.engineers.pop(engineer_id, None)
    state.routes.pop(engineer_id, None)


def import_engineers_csv(
    content: bytes, filename: str, shift_start: datetime, shift_end: datetime,
    district: str | None = None, transport: str | None = None,
) -> dict:
    """Импорт бригад из файла. Район и транспорт берутся ИЗ ФАЙЛА (блок
    «Район» под таблицей и колонка «Транспорт»); district/transport здесь —
    лишь запасные значения для файлов, где их нет. Смена общая на весь файл
    (в файле её нет). Бригада с уже существующим в этом районе именем
    пропускается (повторный импорт того же файла не плодит дубли)."""
    if shift_end <= shift_start:
        raise ValueError("Конец смены должен быть позже её начала")
    parsed = csv_import.import_engineers_csv(content, filename)
    file_district = (parsed.district or district or "").strip()
    if not file_district:
        raise ValueError(
            "В файле не найден район: под таблицей должна быть строка «Район», "
            "а в следующей строке — название района"
        )
    found = _find_office_and_district(file_district)
    if found is None:
        raise ValueError(_no_office_message(file_district))
    file_district = found[1]
    fallback_transport = Transport(transport) if transport else None
    warnings = list(parsed.warnings)
    created: list[Engineer] = []
    skipped = 0
    existing = {(e.name, e.district) for e in state.engineers.values()}
    for p in parsed.engineers:
        eng_transport = p.transport or fallback_transport
        if eng_transport is None:
            warnings.append(csv_import.ImportWarning(
                file=filename, line=p.line, type="no_transport",
                message=f"у бригады «{p.name}» не указан транспорт, строка пропущена",
            ))
            continue
        if (p.name, file_district) in existing:
            skipped += 1
            warnings.append(csv_import.ImportWarning(
                file=filename, line=p.line, type="duplicate_engineer",
                message=f"бригада «{p.name}» уже есть в районе «{file_district}», строка пропущена",
            ))
            continue
        e = add_engineer(
            p.name, [s.value for s in p.skills], shift_start, shift_end,
            eng_transport.value, file_district, sorted(p.equipment),
        )
        created.append(e)
    return {
        "created": created, "skipped_duplicates": skipped,
        "warnings": warnings, "district": file_district,
    }


# ------------------------------------------------------------- заявки

def _normalize_address(address: str) -> str:
    return " ".join(address.strip().lower().split())


def _find_office_by_address(address: str) -> Office | None:
    normalized = _normalize_address(address)
    for office in state.offices.values():
        if _normalize_address(office.address) == normalized:
            return office
    return None


async def import_files(files: list[tuple[str, bytes]]) -> dict:
    """files: список (имя_файла, содержимое).

    Возвращает как общую сводку, так и разбивку по каждому файлу отдельно
    (per_file) — это нужно, чтобы в интерфейсе было видно, какой именно
    файл к какому офису привязался (создал новый или переиспользовал
    существующий) и какие именно предупреждения из какого файла пришли,
    а не просто общие числа.
    """
    created_offices = []
    reused_offices = []
    total_requests = 0
    skipped_duplicate_requests = 0
    warnings: list[str] = []
    per_file: list[dict] = []

    for filename, content in files:
        if filename.lower().endswith(".json"):
            result = csv_import.import_json(content, filename)
        else:
            result = csv_import.import_csv(content, filename)

        warnings.extend(result.warnings)

        file_office = None
        office_action = "none"
        # район файла = result.office_name (см. csv_import.py — office_name
        # всегда равен имени файла без расширения, то же значение, что
        # получает district у каждой заявки из этого файла)
        file_district = result.office_name
        if result.office_address:
            existing = _find_office_by_address(result.office_address)
            if existing is not None:
                # тот же адрес офиса уже есть — не дублируем, используем
                # существующий (имя не трогаем) и просто добавляем ему район
                if file_district not in existing.districts:
                    existing.districts.append(file_district)
                reused_offices.append(existing)
                file_office = existing
                office_action = "reused"
            else:
                office = Office(
                    id=new_id("office"), name=result.office_name, address=result.office_address,
                    districts=[file_district],
                )
                await planner.ensure_office_geocoded(state, office)
                state.offices[office.id] = office
                created_offices.append(office)
                file_office = office
                office_action = "created"

        file_requests_imported = 0
        file_skipped_duplicate = 0
        for req in result.requests:
            if req.id in state.requests:
                # тот же файл (тот же id заявки) уже был импортирован раньше —
                # не затираем текущее состояние (статус/назначение) свежим
                # объектом со статуса "не назначена"
                skipped_duplicate_requests += 1
                file_skipped_duplicate += 1
                continue
            state.requests[req.id] = req
            total_requests += 1
            file_requests_imported += 1

        per_file.append({
            "filename": filename,
            "requests_imported": file_requests_imported,
            "requests_skipped_duplicate": file_skipped_duplicate,
            "office": file_office,
            "office_action": office_action,   # "created" | "reused" | "none"
            "warnings": result.warnings,
        })

    return {
        "created_offices": created_offices,
        "reused_offices": reused_offices,
        "requests_imported": total_requests,
        "skipped_duplicate_requests": skipped_duplicate_requests,
        "warnings": warnings,
        "per_file": per_file,
    }


def add_manual_request(
    address: str, district: str, window_start: datetime, window_end: datetime,
    skill: str, reason: str, duration_min: int, urgent: bool,
    required_transport: str | None, required_equipment: list[str] | None = None,
    connection_type: str | None = None,
) -> Request:
    if not district or not district.strip():
        raise ValueError("Не указан район заявки — обязателен для отбора инженеров")
    skill_enum = Skill(skill)
    req = Request(
        id=new_id("req"),
        address=address,
        district=district.strip(),
        window_start=window_start,
        window_end=window_end,
        skill=skill_enum,
        reason=reason,
        duration_min=duration_min,
        urgent=urgent,
        required_transport=Transport(required_transport) if required_transport else None,
        required_equipment=_clean_items(required_equipment),
        connection_type=_clean_connection_type(connection_type),
        source_file=None,
    )
    state.requests[req.id] = req
    return req


def update_request(
    request_id: str, window_start: datetime | None = None, window_end: datetime | None = None,
    urgent: bool | None = None, required_transport: str | None = "__unset__",
    duration_min: int | None = None, required_equipment: list[str] | None = None,
    connection_type: str | None = "__unset__",
) -> Request:
    """Навык НЕ редактируется (зафиксировано требованиями). Остальные поля,
    включая срочность, — можно: срочность целиком на усмотрение диспетчера,
    никакой автоматики по типу заявки нет."""
    req = state.requests[request_id]
    if window_start is not None:
        req.window_start = window_start
    if window_end is not None:
        req.window_end = window_end
    if urgent is not None:
        req.urgent = urgent
    if duration_min is not None:
        req.duration_min = duration_min
    if required_equipment is not None:
        req.required_equipment = _clean_items(required_equipment)
    if connection_type != "__unset__":
        req.connection_type = _clean_connection_type(connection_type)
    if required_transport != "__unset__":
        req.required_transport = Transport(required_transport) if required_transport else None
    return req


def list_requests() -> list[Request]:
    return list(state.requests.values())


def remove_request(request_id: str) -> None:
    """Убирает заявку из пула. Заявка не теряется безвозвратно — уходит в
    архив state.deleted_requests, откуда её можно мгновенно вернуть кнопкой
    "Вернуть" (см. restore_deleted_request), без повторного ввода вручную."""
    req = state.requests.get(request_id)
    if req is None:
        return
    if req.assigned_engineer_id:
        route = state.routes.get(req.assigned_engineer_id, [])
        state.routes[req.assigned_engineer_id] = [r for r in route if r != request_id]
    state.requests.pop(request_id, None)
    state.explanations.pop(request_id, None)
    state.unassigned.pop(request_id, None)
    state.deleted_requests[request_id] = req


def restore_deleted_request_sync(request_id: str) -> Request:
    """Достаёт заявку из архива удалённых обратно в активный пул (без
    пересчёта плана — пересчёт делает event_restore_deleted_request)."""
    req = state.deleted_requests.pop(request_id, None)
    if req is None:
        raise ValueError("Заявка не найдена среди удалённых (возможно, уже возвращена)")
    req.status = RequestStatus.UNASSIGNED
    req.assigned_engineer_id = None
    return req


# ---------------------------------------------------------------- план

# Все пересчёты плана выполняются строго по одному: фоновый пересчёт после
# импорта не должен пересекаться с ручными событиями (иначе они портят state).
_plan_lock: asyncio.Lock | None = None
_pending_builds = 0


def _lock() -> asyncio.Lock:
    global _plan_lock
    if _plan_lock is None:
        _plan_lock = asyncio.Lock()
    return _plan_lock


def plan_building() -> bool:
    """Идёт (или стоит в очереди) фоновый пересчёт плана."""
    return _pending_builds > 0


def schedule_build() -> bool:
    """Запускает пересчёт плана в фоне и сразу возвращает управление.
    С реальным Router API полный пересчёт может идти минуты — HTTP-запрос
    импорта не должен на нём висеть. Очередь: максимум один работающий
    и один ожидающий пересчёт (остальные были бы дублями)."""
    global _pending_builds
    if _pending_builds >= 2:
        return True

    async def _run():
        global _pending_builds
        try:
            await build_plan()
        except Exception as exc:                      # не роняем сервер фоновой ошибкой
            print(f"[plan] фоновый пересчёт не удался: {exc!r}")
        finally:
            _pending_builds -= 1

    _pending_builds += 1
    asyncio.get_running_loop().create_task(_run())
    return True


async def build_plan() -> Plan:
    async with _lock():
        plan = await planner.build_full_plan(state)
        return _set_last_plan(plan)


async def event_new_request(request: Request) -> Plan:
    async with _lock():
        plan = await planner.event_new_request(state, request)
        return _set_last_plan(plan)


async def event_cancel_request(request_id: str) -> Plan:
    async with _lock():
        plan = await planner.event_cancel_request(state, request_id)
        return _set_last_plan(plan)


async def event_engineer_unavailable(engineer_id: str, reason: str) -> Plan:
    async with _lock():
        plan = await planner.event_engineer_unavailable(state, engineer_id, reason)
        return _set_last_plan(plan)


async def event_engineer_available(engineer_id: str) -> Plan:
    async with _lock():
        plan = await planner.event_engineer_available(state, engineer_id)
        return _set_last_plan(plan)


async def event_restore_request(request_id: str) -> Plan:
    async with _lock():
        plan = await planner.event_restore_request(state, request_id)
        return _set_last_plan(plan)


async def event_restore_deleted_request(request_id: str) -> Plan:
    req = restore_deleted_request_sync(request_id)
    plan = await planner.event_new_request(state, req)
    return _set_last_plan(plan)
