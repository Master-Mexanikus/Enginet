"""Проверка авто-статусов (sent / en_route / in_progress / completed)."""
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from app import serialize
from app.models import RequestStatus

t0 = datetime(2026, 8, 17, 10, 0)
stop = NS(arrival_time=t0 + timedelta(minutes=20), travel_seconds=900,
          service_start=t0 + timedelta(minutes=20), service_end=t0 + timedelta(minutes=80))
f = serialize._dispatch_phase
assert f(stop, None) == "sent"
assert f(stop, t0 + timedelta(minutes=4)) == "sent"          # выезд в 10:05
assert f(stop, t0 + timedelta(minutes=5)) == "en_route"
assert f(stop, t0 + timedelta(minutes=19)) == "en_route"
assert f(stop, t0 + timedelta(minutes=20)) == "in_progress"
assert f(stop, t0 + timedelta(minutes=79)) == "in_progress"
assert f(stop, t0 + timedelta(minutes=80)) == "completed"
print("ВСЕ ПРОВЕРКИ СТАТУСОВ ПРОШЛИ УСПЕШНО")
