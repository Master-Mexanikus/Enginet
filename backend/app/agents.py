"""
Агент-инженер: независимо оценивает одну заявку и либо выбывает из торгов
(с явной причиной), либо делает ставку.

Этап 1 (жёсткий фильтр), в порядке проверки — от дешёвых по вычислениям
критериев к дорогим (поиск вставки в маршрут делается последним и только
если инженер уже прошёл более простые проверки):
    1. доступен ли инженер вообще (не помечен недоступным)
    2. входит ли требуемый навык заявки в навыки инженера
    2а. оборудование: все «требуемые инструменты» заявки плюс дополнительное
        оборудование под тип подключения (FMC/FTTB) должны входить в
        оборудование бригады (подмножество, точное совпадение строк)
    3. если у заявки задан требуемый транспорт — совпадает ли он с транспортом инженера
    4. существует ли хотя бы одна позиция в маршруте, куда заявка физически
       вставляется с соблюдением временного окна и смены

Этап 2 (скоринг) применяется только к тем, кто прошёл этап 1: сначала
побеждает наиболее ШИРОКИЙ универсал (наибольшее число навыков у
инженера), и только при равенстве этого показателя — тот, кто быстрее
прибывает. Логика (уточнена оператором): узкого специалиста некем
подменить, когда заявок именно его профиля не осталось — он просто
простаивает. Универсал же можно занять плотно на весь день чем угодно:
если исчерпались заявки одного профиля, для него найдётся другой. Поэтому
именно универсалам стоит отдавать заявку в первую очередь — так их
расписание останется максимально плотным на протяжении всего дня, а
специалисты выберут то, что осталось именно по их профилю. Это тоже
работает на приоритет №1 (максимум закрытых заявок за день), просто чуть
менее напрямую, чем сам факт отсутствия предпочтения "занятых" инженеров
(см. ниже) — и поэтому идёт даже перед расстоянием: дистанция здесь самый
низкий приоритет, единственный критерий НА ЭТОМ шаге кроме широты
навыков. Приоритет "закрыть заявку" всегда выше приоритета "закрыть её у
ближайшего". Если бы вместо этого здесь уже на первом проходе
предпочитался "уже занятый" инженер ради консолидации, это рисковало бы
забить его расписание и лишить более поздние по очереди заявки вообще
какого-либо подходящего исполнителя — то есть пожертвовать метрикой №1
(число закрытых заявок) ради метрики №2 (число задействованных
исполнителей), а по актуальным приоритетам это неверный компромисс.
Поэтому консолидация вынесена в отдельный, безопасный шаг ПОСЛЕ того, как
все заявки уже получили своего исполнителя — см.
planner.py::_try_consolidate: он переносит уже назначенные заявки на
других занятых инженеров, только если это не отменяет ни одно назначение,
то есть может только улучшить метрику №2, никогда не ухудшая метрику №1.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import Engineer, GeoPoint, Request
from .route_sim import InsertionResult, find_best_insertion

REASON_PRIORITY = {"skill": 0, "district": 1, "equipment": 2, "transport": 2, "shift": 3, "window": 3, "unavailable": 4}


@dataclass
class Bid:
    engineer_id: str
    feasible: bool
    insertion: InsertionResult | None = None
    reason_code: str | None = None    # заполнено, если feasible=False
    already_busy: bool = False        # используется только в тексте объяснения
    skill_breadth: int = 0            # число навыков инженера — больше = более широкий универсал


async def make_bid(
    engineer: Engineer,
    start_point: GeoPoint,
    request_by_id: dict[str, Request],
    current_route_ids: list[str],
    request: Request,
) -> Bid:
    if not engineer.available:
        return Bid(engineer.id, False, reason_code="unavailable")

    if request.skill not in engineer.skills:
        return Bid(engineer.id, False, reason_code="skill")

    if request.district != engineer.district:
        return Bid(engineer.id, False, reason_code="district")

    if not request.all_required_equipment <= engineer.equipment:
        return Bid(engineer.id, False, reason_code="equipment")

    if request.required_transport is not None and request.required_transport != engineer.transport:
        return Bid(engineer.id, False, reason_code="transport")

    insertion = await find_best_insertion(engineer, start_point, request_by_id, current_route_ids, request)
    if not insertion.feasible:
        return Bid(engineer.id, False, reason_code=insertion.failure_reason)

    return Bid(
        engineer.id, True, insertion=insertion,
        already_busy=len(current_route_ids) > 0,
        skill_breadth=len(engineer.skills),
    )


def pick_winner(bids: list[Bid]) -> Bid | None:
    """Среди допустимых ставок побеждает сначала самый широкий универсал
    (больше навыков — его легче занять плотно чем-то ещё, если это
    закончится; специалиста подменить нечем), и только при равенстве —
    самый быстрый по прибытию. Заявка не теряется только из-за того, что
    ближайший занят или далеко: сюда попадают уже исключительно допустимые
    ставки, расстояние и широта навыков лишь упорядочивают их между собой,
    а не отсеивают."""
    feasible = [b for b in bids if b.feasible]
    if not feasible:
        return None

    def sort_key(b: Bid):
        arrival: datetime = b.insertion.new_stop_arrival
        return (-b.skill_breadth, arrival)

    return min(feasible, key=sort_key)


def dominant_rejection_reason(bids: list[Bid]) -> str:
    """Машиночитаемый код доминирующей причины отказа (для бэйджей в UI).

    Полный постатейный разбор (сколько инженеров и по какой причине отпало)
    строится отдельно в explain.py — здесь только сводный код.
    """
    rejected = [b for b in bids if not b.feasible]
    if not rejected:
        return "no_engineers"
    counts: dict[str, int] = {}
    for b in rejected:
        counts[b.reason_code] = counts.get(b.reason_code, 0) + 1
    # при равенстве количеств побеждает более фундаментальная причина
    return min(counts, key=lambda code: (-counts[code], REASON_PRIORITY.get(code, 99)))
