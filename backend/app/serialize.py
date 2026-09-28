from __future__ import annotations

from datetime import datetime, timedelta

from .models import Engineer, Office, Plan, Request, RequestStatus, SKILL_LABELS, TRANSPORT_LABELS


def _dispatch_phase(stop, sim_now: datetime | None) -> str:
    """Фаза распределённой заявки относительно (симулированного) «сейчас»:
    sent — отправлено (всем распределённым; движение ещё не началось),
    en_route — в пути (бригада выехала к заявке),
    in_progress — в работе (бригада на месте и работает),
    completed — завершено (работа закончена, бригада едет дальше).
    Без заданного времени все распределённые заявки — «отправлено»."""
    if sim_now is None:
        return "sent"
    departure = stop.arrival_time - timedelta(seconds=stop.travel_seconds)
    if sim_now < departure:
        return "sent"
    if sim_now < stop.service_start:
        return "en_route"
    if sim_now < stop.service_end:
        return "in_progress"
    return "completed"


def phase_by_request(plan: Plan | None, state, sim_now: datetime | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if plan is None:
        return out
    for route in plan.routes.values():
        for s in route.stops:
            req = state.requests.get(s.request_id)
            if req is not None and req.status == RequestStatus.ASSIGNED:
                out[s.request_id] = _dispatch_phase(s, sim_now)
    return out


def point_dict(point):
    if point is None:
        return None
    return {"lat": point.lat, "lon": point.lon}


def import_warning_dict(w) -> dict:
    return {"file": w.file, "line": w.line, "type": w.type, "message": w.message}


def office_dict(o: Office) -> dict:
    return {
        "id": o.id, "name": o.name, "address": o.address, "point": point_dict(o.point),
        "districts": list(o.districts),
    }


def engineer_dict(e: Engineer) -> dict:
    return {
        "id": e.id,
        "name": e.name,
        "skills": [s.value for s in e.skills],
        "skill_labels": [SKILL_LABELS[s] for s in e.skills],
        "shift_start": e.shift_start.isoformat(),
        "shift_end": e.shift_end.isoformat(),
        "transport": e.transport.value,
        "transport_label": TRANSPORT_LABELS[e.transport],
        "office_id": e.office_id,
        "district": e.district,
        "available": e.available,
        "unavailable_reason": e.unavailable_reason,
        "equipment": sorted(e.equipment),
    }


def request_dict(r: Request, dispatch_phase: str | None = None) -> dict:
    return {
        "id": r.id,
        "address": r.address,
        "district": r.district,
        "window_start": r.window_start.isoformat(),
        "window_end": r.window_end.isoformat(),
        "skill": r.skill.value,
        "skill_label": SKILL_LABELS[r.skill],
        "reason": r.reason,
        "duration_min": r.duration_min,
        "urgent": r.urgent,
        "required_transport": r.required_transport.value if r.required_transport else None,
        "required_equipment": sorted(r.required_equipment),
        "point": point_dict(r.point),
        "status": r.status.value,
        "assigned_engineer_id": r.assigned_engineer_id,
        "source_file": r.source_file,
        "connection_type": r.connection_type,
        "dispatch_phase": dispatch_phase if r.status == RequestStatus.ASSIGNED else None,
    }


def plan_dict(plan: Plan, state, sim_now: datetime | None = None) -> dict:
    if sim_now is None:
        from . import store   # ленивый импорт: store сам импортирует serialize-зависимости
        sim_now = store.get_simulation_time()
    routes_out = {}
    for eid, route in plan.routes.items():
        engineer = state.engineers.get(eid)
        stops = []
        for s in route.stops:
            req = state.requests.get(s.request_id)
            stops.append({
                "request_id": s.request_id,
                "status": req.status.value if req else None,
                "dispatch_phase": (
                    _dispatch_phase(s, sim_now) if req and req.status == RequestStatus.ASSIGNED else None
                ),
                "address": req.address if req else None,
                "point": point_dict(req.point) if req else None,
                "arrival_time": s.arrival_time.isoformat(),
                "service_start": s.service_start.isoformat(),
                "service_end": s.service_end.isoformat(),
                "travel_seconds": s.travel_seconds,
                "distance_meters": s.distance_meters,
                # геометрия участка ОТ предыдущей точки ДО этой остановки (если Router API
                # её вернул); формат — массив [широта, долгота], как ждёт Leaflet Polyline.
                "polyline": [[lat, lon] for lat, lon in s.polyline] if s.polyline else None,
            })
        routes_out[eid] = {
            "engineer_id": eid,
            "engineer_name": engineer.name if engineer else eid,
            "stops": stops,
            "total_distance_meters": route.total_distance_meters,
        }

    return {
        "routes": routes_out,
        "unassigned": [
            {"request_id": u.request_id, "reason_code": u.reason_code, "explanation": u.explanation}
            for u in plan.unassigned
        ],
        "explanations": {
            rid: {"engineer_id": e.engineer_id, "explanation": e.explanation}
            for rid, e in plan.explanations.items()
        },
        "metrics": {
            "unique_engineers": plan.metric_unique_engineers,
            "total_distance_meters": plan.metric_total_distance_meters,
            "distance_by_engineer": plan.metric_distance_by_engineer,
        },
        "built_at": plan.built_at.isoformat(),
        "simulation_time": sim_now.isoformat() if sim_now else None,
    }
