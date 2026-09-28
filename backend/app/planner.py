"""
Оркестрация планирования.

PlannerState хранит текущее состояние сервиса. build_full_plan строит план
с нуля (полный аукцион по незакрытым заявкам + раунды локального улучшения).
Обработчики событий (новая заявка, отмена, недоступность инженера) не
пересчитывают всё с нуля — переторговывают только затронутые заявки поверх
уже согласованного состояния остальных исполнителей.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from . import agents, config, explain, geocoding, route_sim
from .models import (
    AssignmentExplanation, Engineer, EngineerRoute, GeoPoint, Office, Plan,
    Request, RequestStatus, SKILL_QUEUE_RANK, UnassignedInfo,
)


@dataclass
class PlannerState:
    offices: dict[str, Office] = field(default_factory=dict)
    engineers: dict[str, Engineer] = field(default_factory=dict)
    requests: dict[str, Request] = field(default_factory=dict)
    routes: dict[str, list[str]] = field(default_factory=dict)          # engineer_id -> ordered request_ids
    explanations: dict[str, AssignmentExplanation] = field(default_factory=dict)
    unassigned: dict[str, UnassignedInfo] = field(default_factory=dict)
    import_warnings: list[str] = field(default_factory=list)
    deleted_requests: dict[str, Request] = field(default_factory=dict)   # архив удалённых — для мгновенного возврата


# ---------------------------------------------------------------- геокодинг

async def ensure_office_geocoded(state: PlannerState, office: Office) -> None:
    if office.point is None:
        office.point = await geocoding.geocode(office.address)


async def ensure_request_geocoded(state: PlannerState, request: Request) -> None:
    if request.point is None:
        request.point = await geocoding.geocode(request.address)


async def ensure_all_geocoded(state: PlannerState) -> None:
    await asyncio.gather(*(ensure_office_geocoded(state, o) for o in state.offices.values()))
    await asyncio.gather(*(ensure_request_geocoded(state, r) for r in state.requests.values()))


# ------------------------------------------------------------- сортировка

def _priority_order(state: PlannerState, request_ids: list[str]) -> list[str]:
    """Порядок, в котором заявки торгуются аукционом. Три уровня:
    1. «Срочно» — ручной флаг оператора, самый сильный сигнал;
    2. тип заявки: Авария → Новое подключение → Ремонт
       (models.py::SKILL_QUEUE_RANK);
    3. время начала окна — более ранние заявки вперёд.
    Ни аварийность, ни какой-либо другой тип сам по себе срочность не
    определяет — это исключительно ручной флаг оператора."""
    def key(rid: str):
        r = state.requests[rid]
        return (0 if r.urgent else 1, SKILL_QUEUE_RANK[r.skill], r.window_start)
    return sorted(request_ids, key=key)


# ---------------------------------------------------------------- аукцион

async def run_auction_round(state: PlannerState, request_ids: list[str]) -> None:
    """Поочерёдно (в порядке приоритета) торгует каждую заявку из списка
    среди ВСЕХ инженеров ПАРАЛЛЕЛЬНО (одновременный опрос агентов на одну
    заявку), затем сразу фиксирует победителя перед переходом к следующей
    заявке."""
    ordered = _priority_order(state, request_ids)

    for rid in ordered:
        req = state.requests[rid]
        if req.status == RequestStatus.CANCELLED:
            continue

        bids = await asyncio.gather(*(
            agents.make_bid(
                engineer,
                state.offices[engineer.office_id].point,
                state.requests,
                state.routes.get(eid, []),
                req,
            )
            for eid, engineer in state.engineers.items()
        ))

        winner = agents.pick_winner(bids)
        if winner is None:
            code, text = explain.explain_unassigned(req, bids)
            state.unassigned[rid] = UnassignedInfo(rid, code, text)
            req.status = RequestStatus.UNASSIGNED
            req.assigned_engineer_id = None
            continue

        engineer = state.engineers[winner.engineer_id]
        state.routes[winner.engineer_id] = [s.request_id for s in winner.insertion.stops]
        req.status = RequestStatus.ASSIGNED
        req.assigned_engineer_id = winner.engineer_id
        state.unassigned.pop(rid, None)
        state.explanations[rid] = AssignmentExplanation(
            request_id=rid,
            engineer_id=winner.engineer_id,
            explanation=explain.explain_assignment(req, engineer, bids, winner),
        )


# ------------------------------------------------------- локальные улучшения

async def _try_consolidate(state: PlannerState) -> bool:
    """Пытается освободить инженеров с ровно одной заявкой, перенеся её
    к уже занятому инженеру. Это метрика №2 по приоритету (после числа
    закрытых заявок, но перед пробегом) — реализована именно как ОТДЕЛЬНЫЙ
    шаг ПОСЛЕ основного аукциона, а не как критерий выбора победителя
    внутри него: перенос происходит только между заявками, которые УЖЕ
    успешно назначены, поэтому он в принципе не может отменить ни одно
    назначение и ухудшить метрику №1 (число закрытых заявок) — только
    улучшить метрику №2 (число задействованных исполнителей) при прочих
    равных."""
    changed = False
    for eid in [e for e, route in state.routes.items() if len(route) == 1]:
        route = state.routes.get(eid, [])
        if len(route) != 1:
            continue
        rid = route[0]
        req = state.requests[rid]

        best_target_id = None
        best_insertion = None
        for other_id, other_engineer in state.engineers.items():
            if other_id == eid or not other_engineer.available:
                continue
            other_route = state.routes.get(other_id, [])
            if not other_route:
                continue  # перенос на другого свободного инженера не сокращает их число
            if req.skill not in other_engineer.skills:
                continue
            if req.district != other_engineer.district:
                continue
            if not req.all_required_equipment <= other_engineer.equipment:
                continue
            if req.required_transport is not None and req.required_transport != other_engineer.transport:
                continue
            office = state.offices[other_engineer.office_id]
            insertion = await route_sim.find_best_insertion(
                other_engineer, office.point, state.requests, other_route, req
            )
            if insertion.feasible and (
                best_insertion is None or insertion.added_distance_meters < best_insertion.added_distance_meters
            ):
                best_insertion = insertion
                best_target_id = other_id

        if best_target_id is not None:
            old_engineer = state.engineers[eid]
            new_engineer = state.engineers[best_target_id]
            state.routes[best_target_id] = [s.request_id for s in best_insertion.stops]
            state.routes[eid] = []
            req.assigned_engineer_id = best_target_id
            state.explanations[rid] = AssignmentExplanation(
                request_id=rid, engineer_id=best_target_id,
                explanation=(
                    f"Заявка перенесена с инженера «{old_engineer.name}» на «{new_engineer.name}»: "
                    f"перенос сокращает число задействованных исполнителей, все ограничения "
                    f"(навык, оборудование, транспорт, окно, смена) по-прежнему соблюдены."
                ),
            )
            changed = True
    return changed


async def _route_distance(engineer: Engineer, start_point: GeoPoint,
                           request_by_id: dict[str, Request], route_ids: list[str]) -> float | None:
    sim = await route_sim.simulate_route(engineer, start_point, [request_by_id[r] for r in route_ids])
    return sum(s.distance_meters for s in sim.stops) if sim.feasible else None


async def _two_opt_pass(state: PlannerState, engineer_id: str) -> bool:
    """Один проход 2-opt по маршруту инженера: пробует развороты подпоследовательностей,
    применяет первое найденное допустимое улучшение по суммарному пробегу."""
    engineer = state.engineers[engineer_id]
    office = state.offices[engineer.office_id]
    route = state.routes.get(engineer_id, [])
    if len(route) < 3:
        return False

    base_distance = await _route_distance(engineer, office.point, state.requests, route)
    if base_distance is None:
        return False

    for i in range(len(route) - 1):
        for j in range(i + 1, len(route)):
            candidate = route[:i] + list(reversed(route[i:j + 1])) + route[j + 1:]
            dist = await _route_distance(engineer, office.point, state.requests, candidate)
            if dist is not None and dist < base_distance - 1e-6:
                state.routes[engineer_id] = candidate
                return True
    return False


async def run_improvement(state: PlannerState) -> None:
    for _ in range(config.MAX_IMPROVEMENT_ROUNDS):
        changed = await _try_consolidate(state)
        for eid in list(state.routes.keys()):
            if await _two_opt_pass(state, eid):
                changed = True
        if not changed:
            break


# ------------------------------------------------------------------ сборка

async def compose_plan(state: PlannerState) -> Plan:
    routes_out: dict[str, EngineerRoute] = {}
    distance_by_engineer: dict[str, float] = {}
    total_distance = 0.0
    unique_engineers = 0

    for eid, route_ids in state.routes.items():
        engineer = state.engineers[eid]
        office = state.offices[engineer.office_id]
        sim = await route_sim.simulate_route(
            engineer, office.point, [state.requests[r] for r in route_ids]
        )
        routes_out[eid] = EngineerRoute(engineer_id=eid, stops=sim.stops if sim.feasible else [])
        dist = sum(s.distance_meters for s in sim.stops) if sim.feasible else 0.0
        distance_by_engineer[eid] = dist
        total_distance += dist
        if route_ids:
            unique_engineers += 1

    return Plan(
        routes=routes_out,
        unassigned=list(state.unassigned.values()),
        explanations=dict(state.explanations),
        metric_unique_engineers=unique_engineers,
        metric_total_distance_meters=total_distance,
        metric_distance_by_engineer=distance_by_engineer,
        built_at=datetime.utcnow(),
    )


# ------------------------------------------------------------------ API-слой

async def build_full_plan(state: PlannerState) -> Plan:
    state.routes = {eid: [] for eid in state.engineers}
    state.explanations = {}
    state.unassigned = {}
    for req in state.requests.values():
        if req.status != RequestStatus.CANCELLED:
            req.status = RequestStatus.UNASSIGNED
            req.assigned_engineer_id = None

    await ensure_all_geocoded(state)
    target_ids = [rid for rid, r in state.requests.items() if r.status != RequestStatus.CANCELLED]
    await run_auction_round(state, target_ids)
    await run_improvement(state)
    return await compose_plan(state)


async def event_new_request(state: PlannerState, request: Request) -> Plan:
    state.requests[request.id] = request
    await ensure_request_geocoded(state, request)
    await run_auction_round(state, [request.id])
    await run_improvement(state)
    return await compose_plan(state)


async def event_cancel_request(state: PlannerState, request_id: str) -> Plan:
    req = state.requests[request_id]
    req.status = RequestStatus.CANCELLED
    eid = req.assigned_engineer_id
    if eid is not None:
        route = state.routes.get(eid, [])
        state.routes[eid] = [r for r in route if r != request_id]
    req.assigned_engineer_id = None
    state.explanations.pop(request_id, None)
    state.unassigned.pop(request_id, None)

    # освободившееся время может позволить пристроить ранее нераспределённые заявки
    retry_ids = list(state.unassigned.keys())
    if retry_ids:
        await run_auction_round(state, retry_ids)
    await run_improvement(state)
    return await compose_plan(state)


async def event_engineer_unavailable(state: PlannerState, engineer_id: str, reason: str) -> Plan:
    engineer = state.engineers[engineer_id]
    engineer.available = False
    engineer.unavailable_reason = reason

    freed_ids = state.routes.get(engineer_id, [])
    for rid in freed_ids:
        req = state.requests[rid]
        req.status = RequestStatus.UNASSIGNED
        req.assigned_engineer_id = None
        state.explanations.pop(rid, None)
    state.routes[engineer_id] = []

    if freed_ids:
        await run_auction_round(state, freed_ids)
    await run_improvement(state)
    return await compose_plan(state)


async def event_engineer_available(state: PlannerState, engineer_id: str) -> Plan:
    """Возврат инженера в строй — сам по себе не переносит к нему заявки
    (это сделает следующий общий пересчёт/новое событие), но делает его
    снова видимым для будущих аукционов."""
    engineer = state.engineers[engineer_id]
    engineer.available = True
    engineer.unavailable_reason = None
    return await compose_plan(state)


async def event_restore_request(state: PlannerState, request_id: str) -> Plan:
    """Отмена отмены: возвращает ранее отменённую заявку обратно в пул и
    сразу торгует её среди инженеров поверх текущего состояния плана."""
    req = state.requests[request_id]
    req.status = RequestStatus.UNASSIGNED
    req.assigned_engineer_id = None
    await run_auction_round(state, [request_id])
    await run_improvement(state)
    return await compose_plan(state)
