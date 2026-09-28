"""
Проверки патча: оборудование (в т.ч. доп. для FMC/FTTB), импорт бригад. Без сети (fallback-режим).

Запуск:  python3 selfcheck_patch.py
"""
import asyncio
from datetime import datetime

from app import csv_import, planner, store
from app.models import GeoPoint, Request, RequestStatus, Skill


def dt(h, m=0):
    return datetime(2026, 8, 17, h, m)


def _upload(name, content):
    """Файл для обработчиков: настоящий UploadFile (FastAPI), если он установлен."""
    import io
    from fastapi import UploadFile
    try:
        return UploadFile(filename=name, file=io.BytesIO(content))
    except TypeError:
        return UploadFile(name, content)


def fresh_store():
    store.state = planner.PlannerState()
    store._last_plan = None


REQS_CSV = (
    "Заявка;Тип заявки BK;Тип заявки HD;Начало;Окончание;Район;Адрес;Подключение;Гигабитное подключение;Требуемые инструменты\n"
    "1;Локальная заявка;x;17.08.2026 10:00;17.08.2026 18:00;Р;Город Москва, ул. А, д. 1;;Нет;Оптический тестер\n"
    "2;Подключение;x;17.08.2026 10:00;17.08.2026 18:00;Р;Город Москва, ул. Б, д. 2;;Нет;Оптический тестер, Оборудование для подключения\n"
    "3;Глобальная проблема;x;17.08.2026 10:00;17.08.2026 18:00;Р;Город Москва, ул. В, д. 3;;Нет;\n"
    "Адрес Офиса;Город Москва, ул. Офисная, д. 10;;;;;;;;\n"
)


async def main():
    # ---- импорт заявок с колонкой инструментов ----
    fresh_store()
    res = await store.import_files([("vostok.csv", REQS_CSV.encode("cp1251"))])
    assert res["requests_imported"] == 3, res
    r1, r2, r3 = (store.state.requests[f"vostok.csv:{i}"] for i in (1, 2, 3))
    assert r1.required_equipment == {"Оптический тестер"}
    assert r2.required_equipment == {"Оптический тестер", "Оборудование для подключения"}
    assert r3.required_equipment == set()
    print("Колонка «Требуемые инструменты» читается — ок")

    # старый формат без колонки по-прежнему импортируется
    old = csv_import.import_csv(open("sample_data/vostok_sample.csv", "rb").read(), "old.csv")
    assert old.requests and all(r.required_equipment == set() for r in old.requests)
    print("Файл без колонки инструментов импортируется — ок")

    # ---- импорт бригад ----
    out = store.import_engineers_csv(
        open("sample_data/brigady_sample.csv", "rb").read(), "brigady.csv", dt(9), dt(20),
    )
    assert out["district"] == "vostok"
    names = {e.name: e for e in out["created"]}
    assert set(names) == {"Бригада Альфа", "Бригада Бета", "Бригада Гамма"}, names.keys()
    assert names["Бригада Альфа"].skills == {Skill.LOCAL, Skill.CONNECT}
    assert names["Бригада Бета"].skills == {Skill.EMERGENCY, Skill.LOCAL}
    assert names["Бригада Альфа"].equipment == {"Оптический тестер", "Оборудование для подключения"}
    assert all(e.district == "vostok" for e in out["created"])
    from app.models import Transport
    assert {e.name: e.transport for e in out["created"]} == {
        "Бригада Альфа": Transport.CAR, "Бригада Бета": Transport.WALK, "Бригада Гамма": Transport.TRANSIT}
    print("Район и транспорт берутся из файла бригад — ок")
    print("Импорт бригад файлом — ок")
    again = store.import_engineers_csv(
        open("sample_data/brigady_sample.csv", "rb").read(), "brigady.csv", dt(9), dt(20))
    assert again["skipped_duplicates"] == 3 and not again["created"]
    print("Повторный импорт не плодит дубли — ок")
    try:
        store.import_engineers_csv(b"", "x.csv", dt(9), dt(20))
    except ValueError:
        pass
    else:
        raise AssertionError("пустой файл должен давать ошибку")

    # ---- оборудование как жёсткий критерий ----
    plan = await store.build_plan()
    eng_by_name = names
    assert r1.status == RequestStatus.ASSIGNED and r1.assigned_engineer_id in (
        eng_by_name["Бригада Альфа"].id, eng_by_name["Бригада Бета"].id)
    assert r2.status == RequestStatus.ASSIGNED and r2.assigned_engineer_id == eng_by_name["Бригада Альфа"].id, \
        "только у Альфы есть оба нужных инструмента"
    print("Оборудование — жёсткий критерий (подмножество) — ок")

    # у всех убираем оборудование -> заявки с требованиями не назначаются, причина equipment
    for e in store.state.engineers.values():
        e.equipment = set()
    plan = await store.build_plan()
    codes = {u.request_id: u.reason_code for u in plan.unassigned}
    assert codes.get(r1.id) == "equipment" and codes.get(r2.id) == "equipment", codes
    assert r3.status == RequestStatus.ASSIGNED
    print("Причина отказа «equipment» и текст объяснения — ок")
    for e in store.state.engineers.values():
        e.equipment = {"Оптический тестер", "Оборудование для подключения"}
    await store.build_plan()

    # ---- дополнительное оборудование FMC / FTTB ----
    from app.models import EXTRA_EQUIPMENT_FMC, EXTRA_EQUIPMENT_FTTB
    fresh_store()
    csv = (
        "Заявка;Тип заявки BK;Тип заявки HD;Начало;Окончание;Район;Адрес;Подключение;Требуемые инструменты\n"
        "1;Подключение;x;17.08.2026 10:00;17.08.2026 18:00;Р;Город Москва, ул. А, д. 1;FMC;Оборудование для подключения\n"
        "2;Подключение;x;17.08.2026 10:00;17.08.2026 18:00;Р;Город Москва, ул. Б, д. 2;FTTB;Оборудование для подключения\n"
        "3;Подключение;x;17.08.2026 10:00;17.08.2026 18:00;Р;Город Москва, ул. В, д. 3;;Оборудование для подключения\n"
        "Адрес Офиса;Город Москва, ул. Офисная, д. 10;;;;;;;\n"
    )
    await store.import_files([("vostok.csv", csv.encode("cp1251"))])
    q1, q2, q3 = (store.state.requests[f"vostok.csv:{i}"] for i in (1, 2, 3))
    assert (q1.connection_type, q2.connection_type, q3.connection_type) == ("FMC", "FTTB", None)
    assert q1.all_required_equipment == {"Оборудование для подключения", EXTRA_EQUIPMENT_FMC}
    assert q3.all_required_equipment == {"Оборудование для подключения"}
    base = "Оборудование для подключения"
    e_none = store.add_engineer("Без доп", ["connect"], dt(9), dt(20), "car", "vostok", [base])
    e_fmc = store.add_engineer("FMC", ["connect"], dt(9), dt(20), "car", "vostok", [base, EXTRA_EQUIPMENT_FMC])
    e_fttb = store.add_engineer("FTTB", ["connect"], dt(9), dt(20), "car", "vostok", [base, EXTRA_EQUIPMENT_FTTB])
    await store.build_plan()
    assert q1.assigned_engineer_id == e_fmc.id, "FMC-заявка — только бригаде с оборудованием для FMC"
    assert q2.assigned_engineer_id == e_fttb.id, "FTTB-заявка — только бригаде с оборудованием для FTTB"
    assert q3.status == RequestStatus.ASSIGNED, "заявка без FMC/FTTB идёт без доп. оборудования"
    # обычную заявку может взять и бригада с доп. оборудованием, и без
    store.state.engineers.pop(e_fmc.id); store.state.routes.pop(e_fmc.id)
    plan = await store.build_plan()
    assert q1.status == RequestStatus.UNASSIGNED and {u.request_id: u.reason_code for u in plan.unassigned}[q1.id] == "equipment"
    print("Доп. оборудование FMC / FTTB / без — ок")

    # ---- район из имени файла: служебный хвост после «_» отбрасывается ----
    assert csv_import.district_from_filename("Восток_Синтетические_данные_новые_инструменты.csv") == "Восток"
    assert csv_import.district_from_filename("Юго-Восток.csv") == "Юго-Восток"
    assert csv_import.district_from_filename("Югоцентр.csv") == "Югоцентр"
    print("Район из имени файла — ок")

    # ---- API-слой: обработчики вызываются напрямую (без HTTP-сервера) ----
    from fastapi import HTTPException, UploadFile
    from app import main as api, schemas
    fresh_store()
    await api.import_requests([_upload("vostok.csv", REQS_CSV.encode("cp1251"))])
    out = await api.import_engineers(
        _upload("brigady.csv", open("sample_data/brigady_sample.csv", "rb").read()),
        shift_start=dt(9), shift_end=dt(20), district=None, transport=None)
    assert out["engineers_imported"] == 3 and out["district"] == "vostok", out
    assert set(api.get_equipment()) >= {"Оборудование для подключения", "Оптический тестер", "Оборудование для FMC", "Оборудование для FTTB"}
    assert all("required_equipment" in x and "connection_type" in x for x in api.get_requests())
    assert hasattr(api, "put_simulation_time") and not hasattr(api, "event_complete_request")
    e = await api.create_engineer(schemas.EngineerCreate(
        name="Тест", shift_start=dt(9), shift_end=dt(18),
        transport="car", district="VOSTOK", equipment=["Оборудование для ремонта", "Лупа"]))
    assert e["skills"] == ["local"] and e["district"] == "vostok", e   # тип заявок выводится из оборудования
    e2 = await api.edit_engineer(e["id"], schemas.EngineerUpdate(
        equipment=["Оборудование для ремонта", "Оборудование для подключения", "Лупа"]))
    assert sorted(e2["skills"]) == ["connect", "local"]
    try:
        await api.create_engineer(schemas.EngineerCreate(
            name="Без оборудования", shift_start=dt(9), shift_end=dt(18), transport="car",
            district="vostok", equipment=["Лупа"]))
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("без основного оборудования тип заявок не определить")
    rq = await api.create_request(schemas.RequestCreate(
        address="Город Москва, ул. Д, д. 5", district="vostok", window_start=dt(10),
        window_end=dt(19), skill="local", required_equipment=["Лупа"]))
    assert rq["required_equipment"] == ["Лупа"]
    p = await api.edit_request(rq["id"], schemas.RequestUpdate(required_equipment=[]))
    assert p["required_equipment"] == []
    p = await api.edit_request(rq["id"], schemas.RequestUpdate(connection_type="fmc"))
    assert p["connection_type"] == "FMC"
    p = await api.edit_request(rq["id"], schemas.RequestUpdate(clear_connection_type=True))
    assert p["connection_type"] is None
    print("API-обработчики (импорт бригад, оборудование, тип подключения) — ок")

    print("\nВСЕ ПРОВЕРКИ ПАТЧА ПРОШЛИ УСПЕШНО")


if __name__ == "__main__":
    asyncio.run(main())
