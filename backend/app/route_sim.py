"""
Симуляция маршрута инженера и поиск наилучшей позиции для вставки заявки.

Самая нагруженная по вычислениям часть системы. Внутри одного маршрута
(simulate_route) шаги последовательны — время прибытия на остановку зависит
от предыдущей. Разные кандидаты на позицию вставки (find_best_insertion)
друг от друга не зависят и считаются параллельно через asyncio.gather: при
подключённом Yandex Router каждый участок — реальный сетевой запрос, без
параллелизации перебор позиций превращается в цепочку HTTP-запросов.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import routing
from .models import Engineer, GeoPoint, Request, RouteStop, Transport


@dataclass
class SimResult:
    feasible: bool
    stops: list[RouteStop]
    failure_reason: str | None = None   # "window" | "shift" | None
    failure_index: int | None = None    # позиция в маршруте, где случился сбой


async def simulate_route(
    engineer: Engineer,
    start_point: GeoPoint,
    ordered_requests: list[Request],
    enforce_window: bool = True,
) -> SimResult:
    """Прогоняет маршрут от стартовой точки инженера по списку заявок по порядку."""
    current_time = engineer.shift_start
    current_point = start_point
    stops: list[RouteStop] = []

    for i, req in enumerate(ordered_requests):
        assert req.point is not None, f"Заявка {req.id} не геокодирована"
        est = await routing.get_travel(
            current_point, req.point, engineer.transport,
            departure_epoch=int(current_time.timestamp()),
        )
        arrival = current_time + timedelta(seconds=est.duration_seconds)
        service_start = max(arrival, req.window_start)

        if enforce_window and service_start > req.window_end:
            return SimResult(False, stops, "window", i)

        service_end = service_start + timedelta(minutes=req.duration_min)
        if service_end > engineer.shift_end:
            return SimResult(False, stops, "shift", i)

        stops.append(RouteStop(
            request_id=req.id,
            arrival_time=arrival,
            service_start=service_start,
            service_end=service_end,
            travel_seconds=est.duration_seconds,
            distance_meters=est.distance_meters,
            polyline=est.polyline,
        ))
        current_time = service_end
        current_point = req.point

    return SimResult(True, stops)


def _route_distance(stops: list[RouteStop]) -> float:
    return sum(s.distance_meters for s in stops)


@dataclass
class InsertionResult:
    feasible: bool
    position: int | None = None
    stops: list[RouteStop] | None = None          # полный новый маршрут (со вставкой)
    added_distance_meters: float | None = None
    new_stop_arrival: datetime | None = None
    failure_reason: str | None = None             # "window" | "shift" — если нигде не влезло


async def find_best_insertion(
    engineer: Engineer,
    start_point: GeoPoint,
    request_by_id: dict[str, Request],
    current_route_ids: list[str],
    new_request: Request,
) -> InsertionResult:
    """Ищет позицию вставки new_request в текущий маршрут с минимальным приростом пробега.

    Все кандидатные позиции проверяются ПАРАЛЛЕЛЬНО (asyncio.gather) — они
    независимы друг от друга, и при реальных вызовах Router API это даёт
    решающую разницу в скорости отклика по сравнению с перебором по одной
    позиции за раз."""
    current_requests = [request_by_id[rid] for rid in current_route_ids]

    baseline = await simulate_route(engineer, start_point, current_requests, enforce_window=True)
    baseline_distance = _route_distance(baseline.stops) if baseline.feasible else 0.0

    candidates = [
        current_requests[:pos] + [new_request] + current_requests[pos:]
        for pos in range(len(current_requests) + 1)
    ]
    sims = await asyncio.gather(*(
        simulate_route(engineer, start_point, candidate, enforce_window=True)
        for candidate in candidates
    ))

    best: InsertionResult | None = None
    for pos, sim in enumerate(sims):
        if not sim.feasible:
            continue
        added = _route_distance(sim.stops) - baseline_distance
        new_stop = sim.stops[pos]
        if best is None or added < best.added_distance_meters:
            best = InsertionResult(
                feasible=True, position=pos, stops=sim.stops,
                added_distance_meters=added, new_stop_arrival=new_stop.arrival_time,
            )

    if best is not None:
        return best

    # Нигде не влезло с учётом окна — прогоняем те же кандидаты ещё раз без
    # учёта окна (тоже параллельно), только чтобы верно определить причину
    # отказа: не влезает в смену вообще, или именно в окно заявки.
    shift_only_sims = await asyncio.gather(*(
        simulate_route(engineer, start_point, candidate, enforce_window=False)
        for candidate in candidates
    ))
    any_shift_feasible = any(s.feasible for s in shift_only_sims)

    reason = "window" if any_shift_feasible else "shift"
    return InsertionResult(feasible=False, failure_reason=reason)
