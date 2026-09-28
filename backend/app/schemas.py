from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class OfficeUpdate(BaseModel):
    name: str


class EngineerCreate(BaseModel):
    name: str
    skills: list[str] = []            # необязательно: если пусто — выводятся из оборудования
    shift_start: datetime
    shift_end: datetime
    transport: str                    # "car" | "walk" | "bike" | "transit"
    district: str                     # офис определяется автоматически по району
    equipment: list[str] = []


class EngineerUpdate(BaseModel):
    name: Optional[str] = None
    skills: Optional[list[str]] = None
    shift_start: Optional[datetime] = None
    shift_end: Optional[datetime] = None
    transport: Optional[str] = None
    district: Optional[str] = None
    equipment: Optional[list[str]] = None


class EngineerUnavailable(BaseModel):
    reason: str = "Недоступен"


class RequestCreate(BaseModel):
    address: str
    district: str = ""
    window_start: datetime
    window_end: datetime
    skill: str                        # "local" | "connect" | "emergency"
    reason: str = ""
    duration_min: int = 60
    urgent: bool = False
    required_transport: Optional[str] = None
    required_equipment: list[str] = []
    connection_type: Optional[str] = None              # "FMC" | "FTTB" | None (без доп. оборудования)


class RequestUpdate(BaseModel):
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    urgent: Optional[bool] = None
    duration_min: Optional[int] = None
    required_transport: Optional[str] = None
    clear_required_transport: bool = False
    required_equipment: Optional[list[str]] = None      # None = не трогать; [] = снять требования
    connection_type: Optional[str] = None               # None = не трогать
    clear_connection_type: bool = False                 # True = «без дополнительного оборудования»


class NewRequestEvent(RequestCreate):
    pass


class SimulationTimeUpdate(BaseModel):
    time: Optional[datetime] = None                     # None = сбросить симулированное время
