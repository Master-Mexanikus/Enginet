"""
Проверка ядра планировщика на реальном файле заявок, без веб-слоя и без сети
(геокодирование и маршрутизация работают в fallback-режиме).

Запуск:  python3 selfcheck.py
"""
import asyncio
from datetime import datetime

from app import csv_import, planner
from app.models import Engineer, Office, Skill, Transport

SAMPLE = "sample_data/vostok_sample.csv"


def dt(h, m=0):
    return datetime(2026, 8, 17, h, m)


async def main():
    with open(SAMPLE, "rb") as f:
        raw = f.read()
    result = csv_import.import_csv(raw, "vostok.csv")

    print(f"Импортировано заявок: {len(result.requests)}")
    print(f"Адрес офиса: {result.office_address}")
    print(f"Предупреждения импорта: {result.warnings}")

    state = planner.PlannerState()

    office = Office(id="office-vostok", name=result.office_name, address=result.office_address)
    state.offices[office.id] = office

    for r in result.requests:
        state.requests[r.id] = r

    engineers = [
        Engineer("e1", "Иванов", {Skill.LOCAL, Skill.CONNECT}, dt(8), dt(18), Transport.CAR, office.id, "vostok"),
        Engineer("e2", "Петров", {Skill.EMERGENCY, Skill.LOCAL, Skill.CONNECT}, dt(8), dt(20), Transport.CAR, office.id, "vostok"),
        Engineer("e3", "Сидоров", {Skill.LOCAL}, dt(9), dt(17), Transport.WALK, office.id, "vostok"),
        Engineer("e4", "Кузнецов", {Skill.CONNECT, Skill.EMERGENCY}, dt(10), dt(22), Transport.TRANSIT, office.id, "yugo-vostok"),
        Engineer("e5", "Морозов", {Skill.LOCAL, Skill.CONNECT, Skill.EMERGENCY}, dt(8), dt(16), Transport.BIKE, office.id, "vostok"),
    ]
    for e in engineers:
        state.engineers[e.id] = e

    print("\n=== Строим план с нуля ===")
    plan = await planner.build_full_plan(state)

    print(f"Метрика 1 (уникальных исполнителей): {plan.metric_unique_engineers}")
    print(f"Метрика 2 (суммарный пробег, км): {plan.metric_total_distance_meters/1000:.1f}")
    for eid, dist in plan.metric_distance_by_engineer.items():
        n_stops = len(plan.routes[eid].stops)
        if n_stops:
            print(f"  {state.engineers[eid].name}: {n_stops} заявок, {dist/1000:.1f} км")
    print(f"Нераспределено: {len(plan.unassigned)} из {len(state.requests)}")

    reason_counts = {}
    for u in plan.unassigned:
        reason_counts[u.reason_code] = reason_counts.get(u.reason_code, 0) + 1
    print(f"Причины (сводно): {reason_counts}")

    print("\n--- Пример объяснения по назначенной заявке ---")
    if plan.explanations:
        first_key = next(iter(plan.explanations))
        print(plan.explanations[first_key].explanation)

    print("\n--- Пример объяснения по нераспределённой заявке ---")
    if plan.unassigned:
        print(plan.unassigned[0].explanation)

    assigned_ids = [rid for rid, r in state.requests.items() if r.status.value == "assigned"]
    total = len(state.requests)
    print(f"\nПроверка согласованности: assigned={len(assigned_ids)}, "
          f"unassigned={len(plan.unassigned)}, total={total}, "
          f"sum={len(assigned_ids) + len(plan.unassigned)}")
    assert len(assigned_ids) + len(plan.unassigned) == total, "расхождение в подсчёте заявок!"

    # ---- события ----
    print("\n=== Событие: отмена заявки ===")
    some_assigned = assigned_ids[0]
    before = plan.metric_unique_engineers
    plan2 = await planner.event_cancel_request(state, some_assigned)
    print(f"Было исполнителей: {before}, стало: {plan2.metric_unique_engineers}")
    assert state.requests[some_assigned].status.value == "cancelled"

    print("\n=== Событие: инженер недоступен ===")
    busy_engineer_id = max(state.routes, key=lambda k: len(state.routes[k]))
    freed_count = len(state.routes[busy_engineer_id])
    print(f"Инженер {state.engineers[busy_engineer_id].name} с {freed_count} заявками уходит недоступен")
    plan3 = await planner.event_engineer_unavailable(state, busy_engineer_id, "Заболел")
    print(f"После пересчёта: исполнителей={plan3.metric_unique_engineers}, "
          f"нераспределено={len(plan3.unassigned)}")
    assert len(state.routes[busy_engineer_id]) == 0

    print("\n=== Событие: новая срочная заявка ===")
    from app.models import Request
    urgent_req = Request(
        id="urgent-1", address="Город Москва, ул.Талалихина, д. 1",
        district="vostok", window_start=dt(15), window_end=dt(17),
        skill=Skill.EMERGENCY, reason="Полный обрыв линии", duration_min=45, urgent=True,
    )
    plan4 = await planner.event_new_request(state, urgent_req)
    status = state.requests["urgent-1"].status.value
    print(f"Статус срочной заявки после пересчёта: {status}")
    if status == "assigned":
        print(plan4.explanations["urgent-1"].explanation)
    else:
        print([u.explanation for u in plan4.unassigned if u.request_id == "urgent-1"])

    print("\nВСЕ ПРОВЕРКИ ПРОШЛИ УСПЕШНО")

    await check_skill_breadth_tiebreak()


async def check_skill_breadth_tiebreak():
    """Прицельная проверка критерия: при равном времени прибытия заявка
    должна доставаться более широкому универсалу, а не узкому специалисту
    (универсала легче занять плотно чем-то ещё, специалиста подменить нечем)."""
    print("\n=== Проверка: универсал побеждает специалиста при равном прибытии ===")
    from app import agents
    from app.models import GeoPoint, Office as Office_, Request as Request_

    office = Office_(id="off", name="Офис", address="Тестовый адрес")
    office.point = GeoPoint(lat=55.75, lon=37.6)

    same_point = GeoPoint(lat=55.76, lon=37.62)  # одна и та же точка заявки

    specialist = Engineer(
        "spec", "Специалист", {Skill.LOCAL}, dt(8), dt(18), Transport.CAR, office.id, "vostok",
    )
    generalist = Engineer(
        "gen", "Универсал", {Skill.LOCAL, Skill.CONNECT, Skill.EMERGENCY}, dt(8), dt(18),
        Transport.CAR, office.id, "vostok",
    )

    req = Request_(
        id="req-tie", address="Тестовая заявка", district="vostok",
        window_start=dt(9), window_end=dt(20), skill=Skill.LOCAL,
        duration_min=30, urgent=False,
    )
    req.point = same_point

    request_by_id = {req.id: req}
    bids = await asyncio.gather(*(
        agents.make_bid(eng, office.point, request_by_id, [], req)
        for eng in (specialist, generalist)
    ))
    for b in bids:
        assert b.feasible, f"ставка {b.engineer_id} должна быть допустимой в этом тесте"

    winner = agents.pick_winner(bids)
    print(f"Победитель: {winner.engineer_id} (навыков: {winner.skill_breadth})")
    assert winner.engineer_id == "gen", (
        "при равном времени прибытия заявка должна достаться более широкому универсалу, "
        f"а досталась '{winner.engineer_id}'"
    )
    print("Универсал предпочтён специалисту при равном прибытии — ок")

    await check_connect_priority_order()


async def check_connect_priority_order():
    """Приоритет очереди аукциона: Срочно (ручной флаг) → Авария →
    Новое подключение → Ремонт → время окна."""
    print("\n=== Проверка: порядок очереди Авария → Подключение → Ремонт ===")
    from app.planner import PlannerState, _priority_order
    from app.models import Request as Request_, Skill as Skill_

    state = PlannerState()
    common = dict(window_start=dt(9), window_end=dt(20), duration_min=30, district="vostok")
    local_req = Request_(id="r-local", address="A", skill=Skill_.LOCAL, **common)
    emergency_req = Request_(id="r-emergency", address="B", skill=Skill_.EMERGENCY, **common)
    connect_req = Request_(id="r-connect", address="C", skill=Skill_.CONNECT, **common)
    for r in (local_req, emergency_req, connect_req):
        state.requests[r.id] = r

    order = _priority_order(state, [local_req.id, emergency_req.id, connect_req.id])
    print(f"Порядок обработки (без срочных): {order}")
    assert order == ["r-emergency", "r-connect", "r-local"], f"неверный порядок: {order}"
    print("Авария → Новое подключение → Ремонт — ок")

    # ручная срочность перевешивает тип
    local_req.urgent = True
    order2 = _priority_order(state, [local_req.id, emergency_req.id, connect_req.id])
    print(f"Порядок обработки (ремонт вручную помечен срочным): {order2}")
    assert order2[0] == local_req.id, f"ручная срочность должна идти первой, получили {order2}"
    print("Ручная срочность перевешивает тип заявки — ок")

    # при равной срочности и типе — раньше начало окна
    local_req.urgent = False
    late = Request_(id="r-local-late", address="D", skill=Skill_.LOCAL,
                    window_start=dt(12), window_end=dt(20), duration_min=30, district="vostok")
    state.requests[late.id] = late
    order3 = _priority_order(state, [late.id, local_req.id])
    assert order3 == ["r-local", "r-local-late"], order3
    print("Внутри одного типа — по времени окна — ок")


if __name__ == "__main__":
    asyncio.run(main())
