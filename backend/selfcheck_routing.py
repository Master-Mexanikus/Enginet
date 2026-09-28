"""
Проверка парсинга ответа Yandex Router API — без сети, на примерах ответа
из официальной документации (yandex.ru/maps-api/docs/router-api/response.html).

Запуск:  python3 selfcheck_routing.py
"""
import asyncio
import json
from unittest.mock import patch

from app import config, routing
from app.models import GeoPoint, Transport

# Пример ответа для пешего маршрута из документации (один step)
WALKING_RESPONSE = {
    "traffic_type": "forecast",
    "route": {
        "legs": [
            {
                "status": "OK",
                "steps": [
                    {
                        "length": 124,
                        "duration": 89,
                        "mode": "walking",
                        "waiting_duration": 0,
                        "polyline": {
                            "points": [
                                [55.760097, 37.617987],
                                [55.760089, 37.61794],
                                [55.7597, 37.618147],
                                [55.759479, 37.618956],
                            ]
                        },
                    }
                ],
            }
        ]
    },
}

# Пример ответа для автомобильного маршрута из документации (четыре step —
# нужно проверить, что они суммируются, а не берётся только первый)
DRIVING_RESPONSE = {
    "traffic_type": "realtime",
    "route": {
        "legs": [
            {
                "status": "OK",
                "steps": [
                    {"duration": 11.52513027, "length": 44.85900116,
                     "polyline": {"points": [[55.289311, 25.229762], [55.130251, 24.994437]]},
                     "mode": "driving", "waiting_duration": 0},
                    {"duration": 206.4788513, "length": 1116.158936,
                     "polyline": {"points": [[55.289311, 25.229762]]},
                     "mode": "driving", "waiting_duration": 0},
                    {"duration": 1143.630005, "length": 6356.562988,
                     "polyline": {"points": [[55.289311, 25.229762]]},
                     "mode": "driving", "waiting_duration": 0},
                    {"duration": 239.3830109, "length": 524.8220825,
                     "polyline": {"points": [[55.289311, 25.229762]]},
                     "mode": "driving", "waiting_duration": 0},
                ],
            }
        ],
        "flags": {"hasTolls": True, "hasNonTransactionalTolls": False},
    },
}


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


async def main():
    # включаем "как будто есть ключ" для этого теста
    config.YANDEX_ROUTER_API_KEY = "test-key"
    routing._cache.clear()
    routing._stats.update({"yandex_success": 0, "yandex_failure": 0, "fallback_used": 0})

    origin = GeoPoint(lat=55.7, lon=37.6)
    dest = GeoPoint(lat=55.71, lon=37.62)

    print("=== Пеший маршрут (1 step) ===")
    with patch("urllib.request.urlopen", return_value=_FakeResponse(WALKING_RESPONSE)):
        est = await routing.get_travel(origin, dest, Transport.WALK)
    print(f"distance={est.distance_meters}, duration={est.duration_seconds}, source={est.source}")
    assert est.source == "yandex", f"ожидался источник 'yandex', получен '{est.source}'"
    assert est.distance_meters == 124, est.distance_meters
    assert est.duration_seconds == 89, est.duration_seconds
    assert est.polyline is not None and len(est.polyline) == 4
    print("Пеший маршрут распарсен верно — ок")

    routing._cache.clear()
    print("\n=== Автомобильный маршрут (4 step, суммирование) ===")
    with patch("urllib.request.urlopen", return_value=_FakeResponse(DRIVING_RESPONSE)):
        est2 = await routing.get_travel(origin, dest, Transport.CAR, departure_epoch=1700000000)
    expected_length = 44.85900116 + 1116.158936 + 6356.562988 + 524.8220825
    expected_duration = 11.52513027 + 206.4788513 + 1143.630005 + 239.3830109
    print(f"distance={est2.distance_meters:.2f} (ожидалось {expected_length:.2f}), "
          f"duration={est2.duration_seconds:.2f} (ожидалось {expected_duration:.2f})")
    assert abs(est2.distance_meters - expected_length) < 0.01
    assert abs(est2.duration_seconds - expected_duration) < 0.01
    assert est2.polyline is not None and len(est2.polyline) == 5  # 2+1+1+1 точек по шагам
    print("Суммирование по нескольким steps работает верно — ок")

    print("\n=== Проверка названий режимов транспорта ===")
    assert routing._YANDEX_MODE[Transport.BIKE] == "bicycle", "должно быть 'bicycle', не 'cycling'"
    assert routing._YANDEX_MODE[Transport.TRANSIT] == "transit", "должно быть 'transit', не 'masstransit'"
    assert routing._YANDEX_MODE[Transport.CAR] == "driving"
    assert routing._YANDEX_MODE[Transport.WALK] == "walking"
    print("Названия режимов транспорта верны — ок")

    print("\n=== Проверка счётчиков успех/сбой/fallback ===")
    stats = routing.get_stats()
    print(f"stats после двух успешных вызовов: {stats}")
    assert stats["yandex_success"] == 2, stats
    assert stats["yandex_failure"] == 0, stats
    assert stats["fallback_used"] == 0, stats

    # теперь смоделируем сбой API (некорректный JSON) — должен откатиться на fallback
    # и корректно увеличить счётчики failure/fallback_used
    routing._cache.clear()
    dest2 = GeoPoint(lat=55.72, lon=37.63)

    class _BadResponse(_FakeResponse):
        def read(self):
            return b"not valid json"

    with patch("urllib.request.urlopen", return_value=_BadResponse({})):
        est3 = await routing.get_travel(origin, dest2, Transport.CAR)
    assert est3.source == "fallback", f"ожидался откат на fallback, получен '{est3.source}'"
    stats2 = routing.get_stats()
    print(f"stats после смоделированного сбоя API: {stats2}")
    assert stats2["yandex_failure"] == 1, stats2
    assert stats2["fallback_used"] == 1, stats2
    print("Счётчики успех/сбой/fallback считаются верно — ок")

    config.YANDEX_ROUTER_API_KEY = ""  # возвращаем как было
    print("\n=== Проверка: departure_time в прошлом не передаётся в запрос ===")
    config.YANDEX_ROUTER_API_KEY = "test-key"
    routing._cache.clear()

    captured_urls = []
    real_urlopen = __import__("urllib.request", fromlist=["urlopen"]).urlopen

    def _capturing_urlopen(url, *a, **kw):
        captured_urls.append(url)
        return _FakeResponse(WALKING_RESPONSE)

    past_epoch = 1000000000  # 2001 год — заведомо в прошлом
    with patch("urllib.request.urlopen", side_effect=_capturing_urlopen):
        await routing.get_travel(origin, GeoPoint(lat=55.73, lon=37.64), Transport.WALK,
                                  departure_epoch=past_epoch)
    assert "departure_time" not in captured_urls[0], (
        f"departure_time из прошлого не должен попадать в запрос, а он есть в URL: {captured_urls[0]}"
    )
    print("departure_time из прошлого корректно не передаётся — ок")

    routing._cache.clear()
    captured_urls.clear()
    future_epoch = int(__import__("time").time()) + 3600  # через час от реального "сейчас"
    with patch("urllib.request.urlopen", side_effect=_capturing_urlopen):
        await routing.get_travel(origin, GeoPoint(lat=55.74, lon=37.65), Transport.WALK,
                                  departure_epoch=future_epoch)
    assert f"departure_time={future_epoch}" in captured_urls[0], (
        f"departure_time из будущего должен передаваться, а его нет в URL: {captured_urls[0]}"
    )
    print("departure_time из будущего корректно передаётся — ок")

    config.YANDEX_ROUTER_API_KEY = ""  # возвращаем как было
    print("\nВСЕ ПРОВЕРКИ ПАРСИНГА ROUTER API ПРОШЛИ УСПЕШНО")


if __name__ == "__main__":
    asyncio.run(main())
