import asyncio
from datetime import datetime

from app import store


async def main():
    with open("sample_data/vostok_sample.csv", "rb") as f:
        content = f.read()

    result = await store.import_files([("vostok.csv", content)])
    print(f"Импортировано заявок: {result['requests_imported']}")
    print(f"Создано офисов: {[o.name for o in result['created_offices']]}")
    office = result["created_offices"][0]

    # --- срочность НЕ привязана к типу заявки автоматически: при импорте
    # все заявки (включая аварийные) должны прийти НЕ срочными ---
    emergency_reqs = [r for r in store.state.requests.values() if r.skill.value == "emergency"]
    assert emergency_reqs, "в тестовых данных должна быть хотя бы одна аварийная заявка"
    assert not any(r.urgent for r in emergency_reqs), (
        "срочность не должна проставляться автоматически по типу заявки — только вручную оператором"
    )
    print(f"Авария НЕ становится срочной автоматически при импорте — ок ({len(emergency_reqs)} заявок)")

    e1 = store.add_engineer(
        "Иванов", ["local", "connect"], datetime(2026, 8, 17, 8), datetime(2026, 8, 17, 18),
        "car", "vostok",
    )
    e2 = store.add_engineer(
        "Петров", ["emergency", "local", "connect"], datetime(2026, 8, 17, 8), datetime(2026, 8, 17, 20),
        "car", "vostok",
    )
    print(f"Инженеры: {e1.name}, {e2.name}")
    assert e1.office_id == office.id, "офис инженера должен определиться автоматически по району"
    assert "vostok" in office.districts, "офис должен запомнить район файла, из которого создан"
    print("Офис инженера определился автоматически по району — ок")

    # попытка завести инженера в несуществующем районе должна понятно падать
    try:
        store.add_engineer(
            "Никто", ["local"], datetime(2026, 8, 17, 8), datetime(2026, 8, 17, 18),
            "car", "несуществующий-район",
        )
        print("ОШИБКА: инженер в районе без офиса не должен был создаться")
    except ValueError as exc:
        print(f"Ожидаемая ошибка при районе без офиса: {exc}")
        assert "Нет офиса" in str(exc)

    plan = await store.build_plan()
    print(f"План построен: исполнителей={plan.metric_unique_engineers}, "
          f"нераспределено={len(plan.unassigned)}")

    # редактирование профиля
    store.update_engineer(e1.id, name="Иванов И.И.")
    assert store.state.engineers[e1.id].name == "Иванов И.И."
    print("Редактирование профиля инженера — ок")

    # попытка удалить занятого инженера должна упасть
    try:
        store.delete_engineer(e1.id)
        print("ОШИБКА: удаление занятого инженера не должно проходить")
    except ValueError as exc:
        print(f"Ожидаемая ошибка при удалении занятого инженера: {exc}")

    # попытка удалить офис, который используется, должна упасть
    try:
        store.delete_office(office.id)
        print("ОШИБКА: удаление занятого офиса не должно проходить")
    except ValueError as exc:
        print(f"Ожидаемая ошибка при удалении занятого офиса: {exc}")

    # правка временного окна заявки
    some_req_id = next(iter(store.state.requests))
    store.update_request(some_req_id, window_start=datetime(2026, 8, 17, 9), window_end=datetime(2026, 8, 17, 11))
    assert store.state.requests[some_req_id].window_start == datetime(2026, 8, 17, 9)
    print("Правка временного окна заявки — ок")

    # ручное добавление заявки — срочность аварийной заявки НЕ проставляется
    # автоматически, остаётся ровно тем, что указал оператор
    manual = store.add_manual_request(
        "Город Москва, ул.Талалихина, д. 2", "vostok",
        datetime(2026, 8, 17, 15), datetime(2026, 8, 17, 17),
        "emergency", "Тестовая авария", 45, False, None,   # urgent=False, навык аварийный
    )
    print(f"Ручная заявка создана: {manual.id}")
    assert manual.urgent is False, "срочность аварийной заявки не должна проставляться автоматически"
    print("Авария НЕ становится срочной автоматически при ручном создании — ок")

    # оператор может свободно включать и снимать срочность у любой заявки,
    # включая аварийную — никакого автоматического запрета
    store.update_request(manual.id, urgent=True)
    assert store.state.requests[manual.id].urgent is True
    store.update_request(manual.id, urgent=False)
    assert store.state.requests[manual.id].urgent is False
    print("Срочность аварийной заявки свободно включается/снимается вручную — ок")

    # --- дедупликация офисов при повторном импорте того же файла ---
    offices_before = len(store.state.offices)
    result2 = await store.import_files([("vostok.csv", content)])
    offices_after = len(store.state.offices)
    print(f"Офисов до повторного импорта: {offices_before}, после: {offices_after}, "
          f"переиспользовано: {[o.name for o in result2['reused_offices']]}")
    assert offices_after == offices_before, "офис задублировался при повторном импорте того же адреса!"
    assert len(result2["created_offices"]) == 0
    assert len(result2["reused_offices"]) == 1
    print("Дедупликация офисов — ок")

    # --- отмена и возврат заявки ---
    some_assigned_id = next(
        rid for rid, r in store.state.requests.items()
        if r.assigned_engineer_id is not None
    )
    await store.event_cancel_request(some_assigned_id)
    assert store.state.requests[some_assigned_id].status.value == "cancelled"
    print(f"Заявка {some_assigned_id} отменена")

    await store.event_restore_request(some_assigned_id)
    restored_status = store.state.requests[some_assigned_id].status.value
    print(f"После восстановления статус: {restored_status}")
    assert restored_status in ("assigned", "unassigned")  # главное — не cancelled
    print("Восстановление отменённой заявки — ок")

    # --- удаление заявки и её мгновенный возврат из архива ---
    another_id = next(iter(store.state.requests))
    store.remove_request(another_id)
    assert another_id not in store.state.requests
    assert another_id in store.state.deleted_requests
    print(f"Заявка {another_id} удалена и заархивирована")

    await store.event_restore_deleted_request(another_id)
    assert another_id in store.state.requests
    assert another_id not in store.state.deleted_requests
    assert store.state.requests[another_id].status.value != "cancelled"
    print(f"Заявка {another_id} возвращена из архива удалённых — ок")

    print("\nВСЕ ПРОВЕРКИ STORE ПРОШЛИ УСПЕШНО")


if __name__ == "__main__":
    asyncio.run(main())
