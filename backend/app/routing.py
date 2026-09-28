"""
Время и расстояние в пути между двумя точками через Yandex Router API,
с fallback-режимом (нет ключа / нет сети / ошибка API): расстояние по
прямой (haversine) x коэффициент "непрямоты" дороги, время = расстояние
/ средняя скорость для вида транспорта. Обе ветки возвращают одинаковую
структуру (метры, секунды, опционально polyline — только у реального API).
Режимы транспорта и структура ответа сверены с документацией
(yandex.ru/maps-api/docs/router-api/), тесты — в selfcheck_routing.py.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import config
from .models import GeoPoint, Transport

_EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class TravelEstimate:
    distance_meters: float
    duration_seconds: float
    polyline: list[tuple[float, float]] | None = None  # [(lat, lon), ...]
    source: str = "fallback"  # "yandex" | "fallback"


_cache: dict[tuple, TravelEstimate] = {}
_warnings: list[str] = []
_stats = {"yandex_success": 0, "yandex_failure": 0, "fallback_used": 0}

# Лимит одновременных запросов к Router API: параллельный поиск позиции
# вставки (route_sim.py) иначе упирается в лимит Яндекса на конкурентные
# соединения/RPS, запросы падают по таймауту/429 и тихо уходят в fallback.
_CONCURRENCY_LIMIT = 8
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_CONCURRENCY_LIMIT)
    return _semaphore


def _haversine_m(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _fallback_estimate(origin: GeoPoint, dest: GeoPoint, transport: Transport) -> TravelEstimate:
    straight_m = _haversine_m(origin, dest)
    distance_m = straight_m * config.FALLBACK_DETOUR_FACTOR
    speed_kmh = config.FALLBACK_SPEED_KMH[transport.value]
    duration_s = (distance_m / 1000.0) / speed_kmh * 3600.0
    return TravelEstimate(distance_meters=distance_m, duration_seconds=duration_s, source="fallback")


# Соответствие видов транспорта режимам Yandex Router API — сверено
# с официальной документацией (yandex.ru/maps-api/docs/router-api/request.html).
_YANDEX_MODE = {
    Transport.CAR: "driving",
    Transport.WALK: "walking",
    Transport.BIKE: "bicycle",
    Transport.TRANSIT: "transit",
}


def _call_yandex_router_sync(
    origin: GeoPoint, dest: GeoPoint, transport: Transport, departure_epoch: int | None
) -> TravelEstimate | None:
    mode = _YANDEX_MODE[transport]
    params = {
        "apikey": config.YANDEX_ROUTER_API_KEY,
        "waypoints": f"{origin.lat},{origin.lon}|{dest.lat},{dest.lon}",
        "mode": mode,
    }
    # departure_time не может быть в прошлом (Яндекс отвечает 400) — если
    # системная дата демонстрационная и уже "в прошлом", параметр не передаётся,
    # Яндекс берёт прогноз на момент запроса.
    if departure_epoch is not None and departure_epoch >= int(time.time()):
        params["departure_time"] = str(departure_epoch)
    url = config.ROUTER_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=config.HTTP_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if "errors" in data:
            raise ValueError(f"API вернул ошибку: {data['errors']}")

        # leg не содержит единого distance/duration — суммируем по его steps.
        leg = data["route"]["legs"][0]
        if leg.get("status") != "OK":
            raise ValueError(f"не удалось построить маршрут (status={leg.get('status')})")

        steps = leg["steps"]
        distance_m = sum(float(s["length"]) for s in steps)
        duration_s = sum(float(s["duration"]) for s in steps)

        polyline: list[tuple[float, float]] = []
        for s in steps:
            for p in s.get("polyline", {}).get("points", []):
                polyline.append((float(p[0]), float(p[1])))  # [широта, долгота]

        return TravelEstimate(
            distance_meters=distance_m, duration_seconds=duration_s,
            polyline=polyline or None, source="yandex",
        )
    except Exception as exc:
        _warnings.append(f"Router API недоступен ({mode}): {exc}")
        return None


async def get_travel(
    origin: GeoPoint,
    dest: GeoPoint,
    transport: Transport,
    departure_epoch: int | None = None,
) -> TravelEstimate:
    """Возвращает оценку времени/расстояния между двумя точками для транспорта."""
    if origin.lat == dest.lat and origin.lon == dest.lon:
        return TravelEstimate(distance_meters=0.0, duration_seconds=0.0, source="same_point")

    cache_key = (round(origin.lat, 5), round(origin.lon, 5),
                 round(dest.lat, 5), round(dest.lon, 5), transport.value)
    if cache_key in _cache:
        return _cache[cache_key]

    estimate: TravelEstimate | None = None
    if config.YANDEX_ROUTER_API_KEY:
        async with _get_semaphore():
            estimate = await asyncio.to_thread(
                _call_yandex_router_sync, origin, dest, transport, departure_epoch
            )
        if estimate is not None:
            _stats["yandex_success"] += 1
        else:
            _stats["yandex_failure"] += 1

    if estimate is None:
        estimate = _fallback_estimate(origin, dest, transport)
        _stats["fallback_used"] += 1

    _cache[cache_key] = estimate
    return estimate


def get_warnings() -> list[str]:
    return list(_warnings)


def get_stats() -> dict:
    """Сколько раз реально дозвонились до Яндекса, сколько раз откатились
    на fallback — в отличие от is_fallback_mode() (который смотрит только
    на то, задан ли ключ), это показывает, что происходит НА САМОМ ДЕЛЕ."""
    return dict(_stats)


def is_fallback_mode() -> bool:
    return not bool(config.YANDEX_ROUTER_API_KEY)
