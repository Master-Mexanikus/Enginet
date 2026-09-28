export const SKILLS = [
  { value: "local", label: "Ремонт" },
  { value: "connect", label: "Новое подключение" },
  { value: "emergency", label: "Авария" },
];

export const TRANSPORTS = [
  { value: "car", label: "Автомобиль" },
  { value: "walk", label: "Пешеход" },
  { value: "bike", label: "Велосипед" },
  { value: "transit", label: "Общественный транспорт" },
];

export const skillLabel = (v) => SKILLS.find((s) => s.value === v)?.label || v;
export const transportLabel = (v) => TRANSPORTS.find((t) => t.value === v)?.label || v;

// стабильная палитра цветов маршрутов по индексу инженера
const ROUTE_COLORS = [
  "#E8A33D", "#5B8DEF", "#3FA796", "#E1584A", "#B98BE0",
  "#65C5DB", "#D4A574", "#8FBF6B", "#E07AA0", "#7A93B8",
];
export const engineerColor = (index) => ROUTE_COLORS[index % ROUTE_COLORS.length];

export const WARNING_TYPE_LABELS = {
  too_few_columns: "Недостаточно колонок",
  unknown_bk_type: "Неизвестный тип заявки BK",
  invalid_date: "Некорректная дата",
  empty_address: "Пустой адрес",
  no_office_address: "Адрес офиса не найден",
  invalid_skill: "Некорректный навык",
  invalid_transport: "Некорректный транспорт",
  unknown_competence: "Неизвестная компетенция",
  no_skills: "Нет компетенций",
  duplicate_engineer: "Дубликат бригады",
  unknown_transport: "Неизвестный транспорт",
  no_transport: "Не указан транспорт",
};
export const warningTypeLabel = (t) => WARNING_TYPE_LABELS[t] || t;

// Статусы заявки (бейджи)
// Фазы выполнения распределённой заявки (считаются на сервере по времени).
export const PHASE_BADGE = {
  sent: { cls: "badge-info", label: "отправлено" },
  en_route: { cls: "badge-accent", label: "в пути" },
  in_progress: { cls: "badge-warn", label: "в работе" },
  completed: { cls: "badge-ok", label: "завершено" },
};

export const statusBadge = (status, phase) =>
  status === "assigned" && phase && PHASE_BADGE[phase] ? PHASE_BADGE[phase] : STATUS_BADGE[status];

export const STATUS_BADGE = {
  unassigned: { cls: "badge-neutral", label: "не назначена" },
  assigned: { cls: "badge-ok", label: "назначена" },
  cancelled: { cls: "badge-danger", label: "отменена" },
};

// Дополнительное оборудование бригад для работы с FMC / FTTB. Названия —
// ровно как в файле бригад (сравнение на сервере точное).
export const EXTRA_EQUIPMENT = [
  { key: "FMC", label: "Оборудование для FMC" },
  { key: "FTTB", label: "Оборудование для FTTB" },
];
export const EXTRA_EQUIPMENT_NAMES = EXTRA_EQUIPMENT.map((e) => e.label);
// Основное оборудование = тип работ (тип заявок бригады определяется им)
export const MAIN_EQUIPMENT = [
  "Оборудование для ремонта",
  "Оборудование для подключения",
  "Оборудование для аварийных работ",
];
export const NO_EXTRA_LABEL = "Без дополнительного оборудования";
