"""
Шаблонные (не LLM) текстовые объяснения решений — для диспетчера.
"""
from __future__ import annotations

from .agents import Bid, dominant_rejection_reason
from .models import Engineer, Request, SKILL_LABELS

_REASON_LABELS = {
    "skill": "нет требуемого навыка",
    "district": "не привязан к нужному району",
    "equipment": "нет требуемого оборудования",
    "transport": "нет требуемого типа транспорта",
    "shift": "работа не помещается в смену с учётом дороги",
    "window": "не успевает попасть во временное окно заявки",
    "unavailable": "инженер недоступен",
}

_REASON_UNASSIGNED_HEADLINE = {
    "skill": "отсутствует необходимый навык",
    "district": "нет исполнителя, закреплённого за этим районом",
    "equipment": "ни у одного исполнителя нет требуемого оборудования",
    "transport": "нет исполнителя с требуемым типом транспорта",
    "shift": "работа не помещается во временное окно/смену ни у одного исполнителя",
    "window": "работа не помещается во временное окно/смену ни у одного исполнителя",
    "unavailable": "нет свободных исполнителей на требуемое время",
    "no_engineers": "нет ни одного инженера в системе",
}


def explain_assignment(request: Request, engineer: Engineer, bids: list[Bid], winner: Bid) -> str:
    skill_label = SKILL_LABELS[request.skill]
    others = [b for b in bids if b.feasible and b.engineer_id != engineer.id]
    rejected = [b for b in bids if not b.feasible]
    narrower_others = [b for b in others if b.skill_breadth < winner.skill_breadth]

    parts = [
        f"Назначено инженеру «{engineer.name}»: навык «{skill_label}» и район «{request.district}» "
        f"подходят, прибытие — {winner.insertion.new_stop_arrival:%H:%M}."
    ]

    if narrower_others:
        parts.append(
            f"Выбран более универсальный инженер ({winner.skill_breadth} навык(ов) против "
            f"{min(b.skill_breadth for b in narrower_others)} у части конкурентов) — так проще "
            f"занять его другими заявками при нехватке работы по узкому профилю."
        )

    if others:
        parts.append("Среди равных по широте навыков победило более быстрое прибытие.")
    else:
        parts.append("Единственный подходящий инженер по навыку, району, оборудованию, транспорту и окну.")

    if winner.already_busy:
        parts.append("Инженер уже был занят сегодня — новый исполнитель не потребовался.")

    if others:
        parts.append(f"Также подходили: {len(others)} инженер(ов).")

    if rejected:
        by_reason: dict[str, int] = {}
        for b in rejected:
            by_reason[b.reason_code] = by_reason.get(b.reason_code, 0) + 1
        reason_text = "; ".join(f"{_REASON_LABELS[code]} — {n}" for code, n in by_reason.items())
        parts.append(f"Отклонены: {reason_text}.")

    return " ".join(parts)


def explain_unassigned(request: Request, bids: list[Bid]) -> tuple[str, str]:
    """Возвращает (код_причины, текст) для нераспределённой заявки."""
    skill_label = SKILL_LABELS[request.skill]

    if not bids:
        return "no_engineers", "В системе нет ни одного инженера."

    code = dominant_rejection_reason(bids)
    headline = _REASON_UNASSIGNED_HEADLINE[code]

    by_reason: dict[str, int] = {}
    for b in bids:
        if not b.feasible:
            by_reason[b.reason_code] = by_reason.get(b.reason_code, 0) + 1

    breakdown = "; ".join(f"{_REASON_LABELS[c]} — {n}" for c, n in by_reason.items())
    text = f"Не назначена (навык «{skill_label}»): {headline}. Из {len(bids)} кандидатов: {breakdown}."
    return code, text
