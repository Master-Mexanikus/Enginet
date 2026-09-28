"""
Доменные модели.

Сознательно не используется ORM/БД — всё состояние живёт в памяти процесса
(см. store.py) в виде обычных dataclass-объектов. Для хакатон-демо на
15 инженерах и 100 заявках это полностью достаточно и сильно упрощает код.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Skill(str, Enum):
    # Внутренние значения (local/connect/emergency) НЕ менялись — они
    # используются в API, JSON-импорте и на фронтенде; переименованы только
    # отображаемые названия (SKILL_LABELS).
    LOCAL = "local"          # «Ремонт»
    CONNECT = "connect"      # «Новое подключение»
    EMERGENCY = "emergency"  # «Авария»


SKILL_LABELS = {
    Skill.LOCAL: "Ремонт",
    Skill.CONNECT: "Новое подключение",
    Skill.EMERGENCY: "Авария",
}

# Ранг типа заявки в очереди аукциона (меньше = раньше), после ручного
# флага «Срочно»: Авария → Новое подключение → Ремонт.
SKILL_QUEUE_RANK = {
    Skill.EMERGENCY: 0,
    Skill.CONNECT: 1,
    Skill.LOCAL: 2,
}


# Дополнительное оборудование бригад, нужное для работы с типом подключения
# заявки. Названия — ровно как в файле бригад (сравнение точное).
EXTRA_EQUIPMENT_FMC = "Оборудование для FMC"
EXTRA_EQUIPMENT_FTTB = "Оборудование для FTTB"
EXTRA_EQUIPMENT = {
    "FMC": EXTRA_EQUIPMENT_FMC,
    "FTTB": EXTRA_EQUIPMENT_FTTB,
}
NO_EXTRA_EQUIPMENT_LABEL = "Без дополнительного оборудования"

# Основное оборудование = тип работ: тип заявки, который бригада может брать,
# определяется оборудованием (отдельно тип у инженера не выбирается).
EQUIPMENT_TO_SKILL = {
    "Оборудование для ремонта": Skill.LOCAL,
    "Оборудование для подключения": Skill.CONNECT,
    "Оборудование для аварийных работ": Skill.EMERGENCY,
}


class Transport(str, Enum):
    CAR = "car"          # Автомобиль
    WALK = "walk"        # Пешеход
    BIKE = "bike"        # Велосипед
    TRANSIT = "transit"  # Общественный транспорт


TRANSPORT_LABELS = {
    Transport.CAR: "Автомобиль",
    Transport.WALK: "Пешеход",
    Transport.BIKE: "Велосипед",
    Transport.TRANSIT: "Общественный транспорт",
}


class RequestStatus(str, Enum):
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    CANCELLED = "cancelled"


@dataclass
class GeoPoint:
    lat: float
    lon: float


@dataclass
class Office:
    id: str
    name: str
    address: str
    point: Optional[GeoPoint] = None
    # Районы, обслуживаемые этим офисом — заполняется автоматически при
    # импорте (район = имя файла, офисы дедуплицируются по адресу); нужно,
    # чтобы офис инженера определялся по выбранному району автоматически.
    districts: list[str] = field(default_factory=list)


@dataclass
class Engineer:
    id: str
    name: str
    skills: set[Skill]
    shift_start: datetime
    shift_end: datetime
    transport: Transport
    office_id: str
    district: str                          # жёсткая привязка к конкретному району (точное совпадение с Request.district)
    available: bool = True
    unavailable_reason: Optional[str] = None
    # Оборудование бригады. Жёсткий критерий: заявка допустима, только если
    # её required_equipment — подмножество этого набора (точное совпадение строк).
    equipment: set[str] = field(default_factory=set)


@dataclass
class Request:
    id: str
    address: str
    district: str
    window_start: datetime
    window_end: datetime
    skill: Skill
    reason: str = ""                       # свободный текст, informational
    duration_min: int = 60
    urgent: bool = False
    required_transport: Optional[Transport] = None
    required_equipment: set[str] = field(default_factory=set)   # колонка «Требуемые инструменты»
    # Тип подключения (колонка «Подключение»): "FMC" | "FTTB" | None. Для FMC и
    # FTTB нужно дополнительное оборудование; None — «без дополнительного».
    connection_type: Optional[str] = None
    point: Optional[GeoPoint] = None
    status: RequestStatus = RequestStatus.UNASSIGNED
    assigned_engineer_id: Optional[str] = None
    source_file: Optional[str] = None       # из какого файла импортирована

    @property
    def all_required_equipment(self) -> set[str]:
        """Всё оборудование, которое должно быть у бригады: явно требуемое
        плюс дополнительное под тип подключения (FMC/FTTB)."""
        extra = EXTRA_EQUIPMENT.get(self.connection_type or "")
        return self.required_equipment | ({extra} if extra else set())


@dataclass
class RouteStop:
    request_id: str
    arrival_time: datetime          # момент физического прибытия
    service_start: datetime         # момент начала работы (>= window_start)
    service_end: datetime           # service_start + duration
    travel_seconds: float           # время в пути от предыдущей точки
    distance_meters: float          # расстояние от предыдущей точки
    polyline: Optional[list[tuple[float, float]]] = None  # геометрия участка от предыдущей точки (если пришла от Router API)


@dataclass
class EngineerRoute:
    engineer_id: str
    stops: list[RouteStop] = field(default_factory=list)

    @property
    def total_distance_meters(self) -> float:
        return sum(s.distance_meters for s in self.stops)

    @property
    def total_travel_seconds(self) -> float:
        return sum(s.travel_seconds for s in self.stops)


@dataclass
class UnassignedInfo:
    request_id: str
    reason_code: str            # "skill" | "equipment" | "transport" | "time" | "no_engineers"
    explanation: str            # готовый текст для диспетчера


@dataclass
class AssignmentExplanation:
    request_id: str
    engineer_id: str
    explanation: str


@dataclass
class Plan:
    routes: dict[str, EngineerRoute]
    unassigned: list[UnassignedInfo]
    explanations: dict[str, AssignmentExplanation]   # request_id -> explanation
    metric_unique_engineers: int
    metric_total_distance_meters: float
    metric_distance_by_engineer: dict[str, float]
    built_at: datetime
