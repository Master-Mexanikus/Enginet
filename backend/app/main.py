"""
REST API сервиса планирования маршрутов инженеров.

Запуск (из папки backend/):
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000

Ключи Yandex API (необязательны — без них сервис работает в fallback-режиме,
см. app/geocoding.py и app/routing.py):
    export YANDEX_GEOCODER_API_KEY=...
    export YANDEX_ROUTER_API_KEY=...
"""
from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import geocoding, routing, schemas, serialize, store

app = FastAPI(title="Планировщик маршрутов инженеров")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # локальный хакатон-стенд — упрощение осознанное
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
def status():
    return {
        "geocoding_fallback": geocoding.is_fallback_mode(),
        "routing_fallback": routing.is_fallback_mode(),
        "geocoding_warnings": geocoding.get_warnings()[-10:],
        "routing_warnings": routing.get_warnings()[-10:],
        # routing_fallback показывает только отсутствие ключа; если ключ есть,
        # но растёт yandex_failure при нулевом yandex_success — запросы к
        # Router API не проходят (см. routing_warnings).
        "routing_stats": routing.get_stats(),
        "plan_building": store.plan_building(),
    }


# --------------------------------------------------------------- офисы

@app.get("/api/offices")
def get_offices():
    return [serialize.office_dict(o) for o in store.list_offices()]


@app.put("/api/offices/{office_id}")
def edit_office(office_id: str, body: schemas.OfficeUpdate):
    try:
        office = store.update_office(office_id, body.name)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return serialize.office_dict(office)


@app.delete("/api/offices/{office_id}")
def delete_office(office_id: str):
    try:
        store.delete_office(office_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


# ------------------------------------------------------------ инженеры

@app.get("/api/engineers")
def get_engineers():
    return [serialize.engineer_dict(e) for e in store.list_engineers()]


@app.get("/api/districts")
def get_districts():
    """Список районов, встретившихся в заявках — для выбора при создании инженера."""
    return store.list_known_districts()


@app.get("/api/equipment")
def get_equipment():
    """Известное оборудование (у бригад и в заявках) — подсказки для форм."""
    return store.list_known_equipment()


@app.post("/api/engineers/import")
async def import_engineers(
    file: UploadFile = File(...),
    shift_start: datetime = Form(...),
    shift_end: datetime = Form(...),
    district: str | None = Form(None),
    transport: str | None = Form(None),
):
    """Импорт бригад из файла. Район и транспорт читаются из самого файла;
    district/transport — необязательные запасные значения на случай файлов
    без них. Смена (shift_start/shift_end) общая на весь файл."""
    content = await file.read()
    try:
        result = store.import_engineers_csv(
            content, file.filename or "brigady.csv", shift_start, shift_end, district, transport,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"Ошибка импорта: {exc}")
    store.schedule_build()   # пересчёт в фоне: с реальным Router API он долгий
    return {
        "plan_building": True,
        "district": result["district"],
        "engineers_imported": len(result["created"]),
        "skipped_duplicates": result["skipped_duplicates"],
        "engineers": [serialize.engineer_dict(e) for e in result["created"]],
        "warnings": [serialize.import_warning_dict(w) for w in result["warnings"]],
    }


@app.post("/api/engineers")
async def create_engineer(body: schemas.EngineerCreate):
    try:
        engineer = store.add_engineer(
            body.name, body.skills, body.shift_start, body.shift_end,
            body.transport, body.district, body.equipment,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc))
    await store.build_plan()   # новый инженер может изменить оптимальное распределение
    return serialize.engineer_dict(engineer)


@app.put("/api/engineers/{engineer_id}")
async def edit_engineer(engineer_id: str, body: schemas.EngineerUpdate):
    if engineer_id not in store.state.engineers:
        raise HTTPException(404, "Инженер не найден")
    try:
        engineer = store.update_engineer(engineer_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await store.build_plan()   # навык/район/транспорт/смена/офис — все жёсткие критерии
    return serialize.engineer_dict(engineer)


@app.delete("/api/engineers/{engineer_id}")
async def delete_engineer(engineer_id: str):
    try:
        store.delete_engineer(engineer_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await store.build_plan()
    return {"ok": True}


@app.post("/api/engineers/{engineer_id}/unavailable")
async def engineer_unavailable(engineer_id: str, body: schemas.EngineerUnavailable):
    if engineer_id not in store.state.engineers:
        raise HTTPException(404, "Инженер не найден")
    plan = await store.event_engineer_unavailable(engineer_id, body.reason)
    return serialize.plan_dict(plan, store.state)


@app.post("/api/engineers/{engineer_id}/available")
async def engineer_available(engineer_id: str):
    if engineer_id not in store.state.engineers:
        raise HTTPException(404, "Инженер не найден")
    plan = await store.event_engineer_available(engineer_id)
    return serialize.plan_dict(plan, store.state)


# ------------------------------------------------------------- заявки

@app.post("/api/requests/import")
async def import_requests(files: list[UploadFile] = File(...)):
    payload = []
    for f in files:
        content = await f.read()
        payload.append((f.filename, content))
    try:
        result = await store.import_files(payload)
    except Exception as exc:
        raise HTTPException(400, f"Ошибка импорта: {exc}")
    store.schedule_build()
    return {
        "plan_building": True,
        "created_offices": [serialize.office_dict(o) for o in result["created_offices"]],
        "reused_offices": [serialize.office_dict(o) for o in result["reused_offices"]],
        "requests_imported": result["requests_imported"],
        "skipped_duplicate_requests": result["skipped_duplicate_requests"],
        "warnings": [serialize.import_warning_dict(w) for w in result["warnings"]],
        "per_file": [
            {
                "filename": f["filename"],
                "requests_imported": f["requests_imported"],
                "requests_skipped_duplicate": f["requests_skipped_duplicate"],
                "office": serialize.office_dict(f["office"]) if f["office"] else None,
                "office_action": f["office_action"],
                "warnings": [serialize.import_warning_dict(w) for w in f["warnings"]],
            }
            for f in result["per_file"]
        ],
    }


@app.get("/api/requests")
def get_requests():
    phases = serialize.phase_by_request(store.get_last_plan(), store.state, store.get_simulation_time())
    return [serialize.request_dict(r, phases.get(r.id)) for r in store.list_requests()]


@app.post("/api/requests")
async def create_request(body: schemas.RequestCreate):
    try:
        req = store.add_manual_request(
            body.address, body.district, body.window_start, body.window_end,
            body.skill, body.reason, body.duration_min, body.urgent,
            body.required_transport, body.required_equipment, body.connection_type,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # сразу торгуем новую заявку среди инженеров поверх текущего плана,
    # не трогая уже согласованные маршруты остальных
    await store.event_new_request(req)
    return serialize.request_dict(req)


@app.patch("/api/requests/{request_id}")
async def edit_request(request_id: str, body: schemas.RequestUpdate):
    if request_id not in store.state.requests:
        raise HTTPException(404, "Заявка не найдена")
    if body.clear_required_transport:
        required_transport = None            # явно снять ограничение по транспорту
    elif body.required_transport is not None:
        required_transport = body.required_transport
    else:
        required_transport = "__unset__"      # поле не трогаем
    if body.clear_connection_type:
        connection_type = None                # явно «без дополнительного оборудования»
    elif body.connection_type is not None:
        connection_type = body.connection_type
    else:
        connection_type = "__unset__"         # поле не трогаем
    try:
        req = store.update_request(
            request_id, body.window_start, body.window_end, body.urgent,
            required_transport, body.duration_min, body.required_equipment, connection_type,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await store.build_plan()   # окно/длительность/транспорт — тоже критерии отбора
    return serialize.request_dict(req)


@app.delete("/api/requests/{request_id}")
async def delete_request(request_id: str):
    if request_id not in store.state.requests:
        raise HTTPException(404, "Заявка не найдена")
    store.remove_request(request_id)
    await store.build_plan()
    return {"ok": True}


@app.post("/api/requests/{request_id}/restore")
async def restore_deleted_request(request_id: str):
    if request_id not in store.state.deleted_requests:
        raise HTTPException(404, "Заявка не найдена среди удалённых")
    plan = await store.event_restore_deleted_request(request_id)
    return serialize.plan_dict(plan, store.state)


# ---------------------------------------------------------------- план

@app.post("/api/plan/build")
async def build_plan():
    plan = await store.build_plan()
    return serialize.plan_dict(plan, store.state)


@app.get("/api/plan")
def get_plan():
    plan = store.get_last_plan()
    if plan is None:
        raise HTTPException(404, "План ещё не построен — вызовите POST /api/plan/build")
    return serialize.plan_dict(plan, store.state)


# -------------------------------------------------------------- события

@app.post("/api/events/new-request")
async def event_new_request(body: schemas.NewRequestEvent):
    try:
        req = store.add_manual_request(
            body.address, body.district, body.window_start, body.window_end,
            body.skill, body.reason, body.duration_min, body.urgent,
            body.required_transport, body.required_equipment, body.connection_type,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # add_manual_request уже кладёт заявку в state.requests; событию нужно
    # только прогнать для неё аукцион и пересчитать план
    plan = await store.event_new_request(req)
    return serialize.plan_dict(plan, store.state)


@app.post("/api/events/cancel-request/{request_id}")
async def event_cancel_request(request_id: str):
    if request_id not in store.state.requests:
        raise HTTPException(404, "Заявка не найдена")
    plan = await store.event_cancel_request(request_id)
    return serialize.plan_dict(plan, store.state)


@app.post("/api/events/restore-request/{request_id}")
async def event_restore_request(request_id: str):
    if request_id not in store.state.requests:
        raise HTTPException(404, "Заявка не найдена")
    if store.state.requests[request_id].status.value != "cancelled":
        raise HTTPException(400, "Заявка не отменена — нечего возвращать")
    plan = await store.event_restore_request(request_id)
    return serialize.plan_dict(plan, store.state)


# ------------------------------------------------- симулированное время

@app.get("/api/simulation-time")
def get_simulation_time():
    t = store.get_simulation_time()
    return {"time": t.isoformat() if t else None}


@app.put("/api/simulation-time")
def put_simulation_time(body: schemas.SimulationTimeUpdate):
    """Статусы «Отправлено / В пути / В работе / Завершено» вычисляются
    относительно этого времени; None — сброс (все распределённые — «Отправлено»)."""
    t = store.set_simulation_time(body.time)
    return {"time": t.isoformat() if t else None}
