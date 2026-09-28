"""
Геокодирование текстовых адресов в координаты.

Основной путь — Yandex Geocoder API. Если ключ не задан, либо запрос не
удался (нет сети, исчерпана квота), сервис не падает и не блокирует
демонстрацию: включается детерминированный fallback, который превращает
строку адреса в стабильные псевдо-координаты в пределах Москвы и области
(один и тот же адрес всегда даёт одну и ту же точку, но координаты не
соответствуют реальному расположению дома).

Результаты кэшируются по нормализованной строке адреса на время жизни
процесса — при повторном использовании того же адреса запрос к API не
повторяется.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import urllib.parse
import urllib.request

from . import config
from .models import GeoPoint

# Примерный bounding box Москвы и ближнего Подмосковья — используется только
# для fallback-режима, чтобы точки выглядели правдоподобно на карте.
_FALLBACK_LAT_RANGE = (55.55, 55.90)
_FALLBACK_LON_RANGE = (37.35, 37.85)

_cache: dict[str, GeoPoint] = {}
_warnings: list[str] = []


def _normalize(address: str) -> str:
    return " ".join(address.strip().lower().split())


def _fallback_point(address: str) -> GeoPoint:
    """Стабильный псевдо-геокодинг на основе хэша адреса."""
    h = hashlib.sha256(_normalize(address).encode("utf-8")).hexdigest()
    frac_lat = int(h[:8], 16) / 0xFFFFFFFF
    frac_lon = int(h[8:16], 16) / 0xFFFFFFFF
    lat = _FALLBACK_LAT_RANGE[0] + frac_lat * (_FALLBACK_LAT_RANGE[1] - _FALLBACK_LAT_RANGE[0])
    lon = _FALLBACK_LON_RANGE[0] + frac_lon * (_FALLBACK_LON_RANGE[1] - _FALLBACK_LON_RANGE[0])
    return GeoPoint(lat=round(lat, 6), lon=round(lon, 6))


def _call_yandex_geocoder_sync(address: str) -> GeoPoint | None:
    params = {
        "apikey": config.YANDEX_GEOCODER_API_KEY,
        "geocode": address,
        "format": "json",
        "results": 1,
    }
    url = config.GEOCODER_URL + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=config.HTTP_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        members = data["response"]["GeoObjectCollection"]["featureMember"]
        if not members:
            return None
        pos = members[0]["GeoObject"]["Point"]["pos"]  # "lon lat"
        lon_str, lat_str = pos.split()
        return GeoPoint(lat=float(lat_str), lon=float(lon_str))
    except Exception as exc:  # сеть недоступна, квота, невалидный ответ и т.п.
        _warnings.append(f"Geocoder API недоступен для '{address}': {exc}")
        return None


async def geocode(address: str) -> GeoPoint:
    """Возвращает координаты адреса, используя кэш / API / fallback."""
    key = _normalize(address)
    if key in _cache:
        return _cache[key]

    point: GeoPoint | None = None
    if config.YANDEX_GEOCODER_API_KEY:
        point = await asyncio.to_thread(_call_yandex_geocoder_sync, address)

    if point is None:
        point = _fallback_point(address)

    _cache[key] = point
    return point


def get_warnings() -> list[str]:
    return list(_warnings)


def is_fallback_mode() -> bool:
    return not bool(config.YANDEX_GEOCODER_API_KEY)
