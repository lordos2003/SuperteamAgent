"""Политика отбора: финансы, регион, оплата, тип задачи и пригодность для агента.

Фильтры применяются ТОЛЬКО после верификации первоисточника: задача, открытость
которой не подтверждена, в recommended-списки не попадает.

Жёсткие правила (по требованию задания):
  * любая обязательная реальная финансовая активность исполнителя → ``EXCLUDE``
    (используется существующий :func:`superteam_agent.risk.analyze_financial_risk`);
  * неизвестный финансовый риск НЕ считается безопасным (``UNKNOWN`` → ручная
    проверка, см. ``ALLOW_UNKNOWN_FINANCIAL_RISK_IN_TOP``);
  * ``Russia explicitly excluded`` → ``agent_compatible = false``;
  * неизвестный регион НЕ считается подходящим автоматически;
  * нет суммы награды («paid bounty» без цифр) → ``EXCLUDE``;
  * self-promotion / for hire / volunteer / unpaid good-first-issue → ``EXCLUDE``.
"""
from __future__ import annotations

import re
from typing import Any, Final, Mapping

from ..config import (
    ALLOW_MEDIUM_FINANCIAL_RISK_IN_TOP,
    ALLOW_UNKNOWN_FINANCIAL_RISK_IN_TOP,
    ALLOW_UNKNOWN_REGION_IN_TOP,
    BOUNTY_ASSIGNED,
    BOUNTY_CLAIMED,
    BOUNTY_CLOSED,
    BOUNTY_PR_LINKED,
    BOUNTY_UNKNOWN,
    BOUNTY_VERIFIED_OPEN,
    FINANCIAL_RISK_UNKNOWN,
    MIN_REWARD_USD,
    MIN_TEXT_FOR_FINANCIAL_LOW,
    PAYMENT_TYPE_CRYPTO,
    PAYMENT_TYPE_FIAT,
    PAYMENT_TYPE_UNKNOWN,
)
from ..risk import (
    FINANCIAL_RISK_HIGH,
    FINANCIAL_RISK_LOW,
    FINANCIAL_RISK_MEDIUM,
    REAL_ACTIVITY_EXCLUSION,
    analyze_financial_risk,
)
from ..scoring import detect_skills, estimate_difficulty
from .models import (
    BOUNTY_AVAILABLE,
    BOUNTY_CLAIMED,
    BOUNTY_PAID,
    BOUNTY_STATUS_UNKNOWN,
    BOUNTY_TAKEN,
    REGION_GLOBAL,
    REGION_RESTRICTED,
    REGION_RUSSIA_ALLOWED,
    REGION_RUSSIA_EXCLUDED,
    REGION_UNKNOWN,
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    parse_estimated_time,
    payment_type_for,
)
from .verification import verification_exclusion

#: Приоритет технологий из задания (индекс меньше — приоритетнее).
TECH_PRIORITY: Final[tuple[str, ...]] = (
    "python",
    "javascript",
    "html/css",
    "playwright",
    "web scraping",
    "automation",
    "csv/excel",
    "api",
    "testing/qa",
    "frontend",
    "backend",
)

#: Маркеры self-promotion / найма (не задача для внешнего исполнителя).
SELF_PROMO_MARKERS: Final[tuple[str, ...]] = (
    "[for hire]",
    "for hire",
    "we are hiring",
    "hiring a",
    "looking for a developer",
    "looking for developers",
    "join our team",
    "seeking a cofounder",
)
#: Маркеры волонтёрских/неоплачиваемых задач.
UNPAID_MARKERS: Final[tuple[str, ...]] = (
    "volunteer",
    "unpaid",
    "no payment",
    "without payment",
    "pro bono",
    "not paid",
)
#: Нетехнические задачи — подходят человеку, а не агенту-разработчику.
HUMAN_ONLY_MARKERS: Final[tuple[str, ...]] = (
    "logo",
    "poster",
    "banner",
    "video edit",
    "video editing",
    "graphic design",
    "illustration",
    "ui/ux design",
    "figma design",
    "write an article",
    "blog post",
    "newsletter",
    "translation",
    "voice over",
    "meme",
    "merch",
)

#: Регион: явное исключение России/санкционные формулировки.
RUSSIA_EXCLUDED_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?:not|isn't|is not|no)\s+(?:available|open|eligible|permitted)[^.]{0,40}\brussia\b", re.I),
    re.compile(r"\brussia\b[^.]{0,40}\b(?:excluded|not eligible|ineligible|not allowed|not available)\b", re.I),
    re.compile(r"\bexclud(?:e|ing|ed)\s+russia\b", re.I),
    re.compile(r"sanction(?:s|ed)?\s+(?:countries|regions|jurisdictions)", re.I),
    re.compile(r"\bofac\b", re.I),
)
#: Регион: ограничение конкретными странами.
RESTRICTED_REGION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"only\s+(?:available|open)\s+to\s+(?:residents|people|citizens|users)", re.I),
    re.compile(r"\bmust\s+(?:be|reside|live|have)[^.]{0,50}\b(?:resident|citizen|country)", re.I),
    re.compile(r"\b(?:us|usa|u\.s\.|uk|europe|eu)\s+only\b", re.I),
    re.compile(r"\beligible countries\b", re.I),
    re.compile(r"restricted to\b", re.I),
    re.compile(r"not available in your (?:country|region|location)", re.I),
    re.compile(r"\bresidents? of [A-Z][a-z]+ only\b", re.I),
)
#: Регион: явная глобальность.
GLOBAL_REGION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bworldwide\b", re.I),
    re.compile(r"\banywhere in the world\b", re.I),
    re.compile(r"open to (?:everyone|all|anyone)\b", re.I),
    re.compile(r"no (?:geographic|regional|country) restriction", re.I),
    re.compile(r"\bglobal(?:ly)?\s+(?:remote|program|bounty|challenge|competition)\b", re.I),
    re.compile(r"\bremote\b[^.]{0,20}\b(?:ok|friendly|work|position|role)\b", re.I),
)
#: Регион: явное разрешение России (без слова «available» — оно встречается в
#: формулировках запрета, например «not available in Russia»).
RUSSIA_ALLOWED_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\brussia\b[^.]{0,40}\b(?:is\s+)?(?:eligible|allowed|welcome|supported)\b", re.I),
    re.compile(r"\b(?:eligible|allowed|welcome|supported)\b[^.]{0,25}\brussia\b", re.I),
)


def _first_match(patterns: tuple[re.Pattern[str], ...], text: str) -> str:
    """Найти первое совпадение и вернуть его короткий текст (для доказательства)."""
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return " ".join(match.group(0).split())[:120]
    return ""


def analyze_region(text: str) -> dict[str, Any]:
    """Определить региональный статус задачи.

    :returns: ``{"region", "eligible_for_russia", "reasons"}``. Значения не
        додумываются: если в тексте нет региональной информации —
        ``region = UNKNOWN`` (и задача НЕ считается автоматически подходящей).
    """
    if not (text or "").strip():
        return {
            "region": REGION_UNKNOWN,
            "eligible_for_russia": None,
            "reasons": ["no task text: region unknown"],
        }

    # Сначала запреты/санкции: «not available in Russia» не должно читаться как разрешение.
    excluded = _first_match(RUSSIA_EXCLUDED_PATTERNS, text)
    if excluded:
        return {
            "region": REGION_RUSSIA_EXCLUDED,
            "eligible_for_russia": False,
            "reasons": [f"Russia explicitly excluded/sanctioned: '{excluded}'"],
        }

    allowed = _first_match(RUSSIA_ALLOWED_PATTERNS, text)
    if allowed:
        return {
            "region": REGION_RUSSIA_ALLOWED,
            "eligible_for_russia": True,
            "reasons": [f"explicit Russia allowance: '{allowed}'"],
        }

    restricted = _first_match(RESTRICTED_REGION_PATTERNS, text)
    if restricted:
        return {
            "region": REGION_RESTRICTED,
            "eligible_for_russia": None,
            "reasons": [f"regional restriction: '{restricted}'"],
        }

    global_hit = _first_match(GLOBAL_REGION_PATTERNS, text)
    if global_hit:
        return {
            "region": REGION_GLOBAL,
            "eligible_for_russia": None,
            "reasons": [f"explicitly global/worldwide: '{global_hit}'"],
        }

    return {
        "region": REGION_UNKNOWN,
        "eligible_for_russia": None,
        "reasons": ["region not stated in task text -> manual check required"],
    }


def analyze_task_text(text: str) -> dict[str, Any]:
    """Оценить технологический стек, сложность и пригодность для новичка/агента.

    Используются существующие анализаторы проекта (:func:`detect_skills`,
    :func:`estimate_difficulty`), поэтому оценки согласованы с логикой Superteam.
    """
    skills_info = detect_skills(text or "")
    difficulty_info = estimate_difficulty(text or "")
    lowered = (text or "").lower()

    skills = [str(skill) for skill in skills_info.get("skills") or []]
    lowered_skills = {skill.lower() for skill in skills}
    priority = 99
    for index, tech in enumerate(TECH_PRIORITY):
        if tech in lowered_skills:
            priority = min(priority, index)
    if priority == 99 and skills:
        priority = len(TECH_PRIORITY)  # известный стек, но не из приоритетного списка

    estimated_time = parse_estimated_time(text or "")
    difficulty = str(difficulty_info.get("difficulty") or "UNKNOWN")
    hours = 0
    match = re.match(r"^(\d+)", estimated_time)
    if match:
        hours = int(match.group(1))

    beginner_friendly = bool(
        difficulty == "EASY"
        or (hours and hours <= 5)
        or "good first issue" in lowered
        or "good-first-issue" in lowered
    )
    human_markers = [marker for marker in HUMAN_ONLY_MARKERS if marker in lowered]
    return {
        "tech_stack": skills,
        "tech_priority": priority,
        "difficulty": difficulty,
        "difficulty_indicators": difficulty_info.get("indicators") or [],
        "estimated_time": estimated_time,
        "beginner_friendly": beginner_friendly,
        "human_markers": human_markers,
        "is_code_task": bool(skills) and not human_markers,
    }


def analyze_reward(candidate: Mapping[str, Any], verification: Mapping[str, Any]) -> dict[str, Any]:
    """Определить награду, валюту и тип выплаты (без выдумывания сумм).

    Сумма берётся из данных источника или из первоисточника (labels/title/body
    issue, bounty-комментарии платформ).
    """
    amount = candidate.get("reward_amount")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        amount = None
    currency = str(candidate.get("reward_currency") or "").strip()

    if amount is None:
        verified_amount = verification.get("reward_amount")
        if isinstance(verified_amount, (int, float)) and not isinstance(verified_amount, bool):
            amount = float(verified_amount)
            currency = currency or str(verification.get("reward_currency") or "")
    if amount is not None and not currency:
        currency = str(verification.get("reward_currency") or "")

    payment_type = payment_type_for(currency)
    if payment_type == PAYMENT_TYPE_UNKNOWN and amount is None:
        payment_type = PAYMENT_TYPE_UNKNOWN

    has_reward = bool(amount is not None and amount > 0)
    small_reward = bool(has_reward and amount is not None and amount < 25)
    return {
        "reward_amount": amount,
        "reward_currency": currency,
        "payment_type": payment_type,
        "has_reward": has_reward,
        "small_reward": small_reward,
        "meets_minimum": bool(has_reward and amount is not None and amount >= MIN_REWARD_USD),
        "reason": (
            f"reward: {amount} {currency or 'UNKNOWN'} ({payment_type})"
            if has_reward
            else "no reward amount found (paid bounty without a sum is not accepted)"
        ),
    }


#: Минимальная длина описания, при которой финансовый риск можно считать LOW,
#: импортируется из конфига (общее значение для card verification и multi-source).


def evaluate(candidate: Mapping[str, Any], verification: Mapping[str, Any]) -> dict[str, Any]:
    """Применить всю политику к задаче после верификации первоисточника.

    :param candidate: запись единого формата (см. :mod:`.models`).
    :param verification: результат проверки первоисточника
        (:func:`..core.verification.verify_github_issue` или адаптированный
        результат проверки карточки Superteam).
    :returns: словарь с итоговыми полями задачи, списком причин исключения,
        тегом лога и отдельным списком причин ручной проверки.
    """
    title = str(candidate.get("title") or "")
    description = str(candidate.get("description") or "")
    requirements = str(candidate.get("requirements_text") or "")
    eligibility = str(candidate.get("eligibility_text") or "")
    labels_text = " ".join(str(label) for label in candidate.get("labels") or [])
    reward_evidence = " ".join(str(item) for item in verification.get("reward_evidence") or [])
    text = " ".join(part for part in (title, description, requirements, eligibility, labels_text) if part)
    reward_text = " ".join(part for part in (text, reward_evidence) if part)

    verified_status = str(verification.get("verified_status") or BOUNTY_UNKNOWN)
    verification_reason, verification_tag = verification_exclusion(verified_status)

    reward = analyze_reward(candidate, verification)
    task = analyze_task_text(text)
    region = analyze_region(text)

    # --- финансовый риск: используется существующий анализатор проекта ---
    risk = analyze_financial_risk(description or title, requirements, eligibility)
    clean_description = (description or "").strip()
    substantive_text = len(clean_description) >= MIN_TEXT_FOR_FINANCIAL_LOW and (
        clean_description.lower() != title.strip().lower()
    )

    if risk["hard_exclusion"]:
        financial_risk = FINANCIAL_RISK_HIGH
    elif not substantive_text:
        # Текст слишком короткий, чтобы утверждать безопасность -> UNKNOWN.
        financial_risk = FINANCIAL_RISK_UNKNOWN
    elif risk["financial_risk"] == FINANCIAL_RISK_MEDIUM:
        financial_risk = FINANCIAL_RISK_MEDIUM
    else:
        financial_risk = FINANCIAL_RISK_LOW

    note = (
        ""
        if substantive_text
        else f"task text too short ({len(description.strip())} chars) to confirm no own-money requirement"
    )
    return _decide(
        candidate=candidate,
        verification=verification,
        reward=reward,
        task=task,
        region=region,
        risk=risk,
        financial_risk=financial_risk,
        reward_text=reward_text,
        verified_status=verified_status,
        verification_reason=verification_reason,
        verification_tag=verification_tag,
        short_text_note=note,
    )


def _decide(
    *,
    candidate: Mapping[str, Any],
    verification: Mapping[str, Any],
    reward: Mapping[str, Any],
    task: Mapping[str, Any],
    region: Mapping[str, Any],
    risk: Mapping[str, Any],
    financial_risk: str,
    reward_text: str,
    verified_status: str,
    verification_reason: str,
    verification_tag: str,
    short_text_note: str,
) -> dict[str, Any]:
    """Свести результаты анализа в решение и списки причин (внутренняя функция)."""
    lowered = reward_text.lower()
    exclusions: list[str] = []
    manual_reasons: list[str] = []
    exclusion_tag = ""

    def add(reason: str, tag: str) -> None:
        nonlocal exclusion_tag
        exclusions.append(reason)
        if not exclusion_tag:
            exclusion_tag = tag

    # 1. Верификация первоисточника — самое важное условие.
    if verification_reason:
        add(verification_reason, verification_tag or "[EXCLUDED][UNVERIFIED]")

    # 2. Награда должна быть подтверждена суммой (не «paid bounty» без цифр).
    if not reward.get("meets_minimum"):
        add("NO_CONFIRMED_REWARD", "[EXCLUDED][NO_REWARD]")

    # 3. Задача должна быть для внешнего исполнителя и оплачиваемой.
    if any(marker in lowered for marker in SELF_PROMO_MARKERS):
        add("SELF_PROMOTION_OR_FOR_HIRE", "[EXCLUDED][SELF_PROMOTION]")
    if any(marker in lowered for marker in UNPAID_MARKERS) and reward.get("payment_type") == PAYMENT_TYPE_UNKNOWN:
        add("UNPAID_OR_VOLUNTEER", "[EXCLUDED][UNPAID]")
    if verification.get("aggregator_markers"):
        add("AGGREGATOR_POST_NOT_A_TASK", "[EXCLUDED][AGGREGATOR]")

    # 4. Финансовый фильтр (жёсткий).
    if financial_risk == FINANCIAL_RISK_HIGH:
        add(REAL_ACTIVITY_EXCLUSION, "[EXCLUDED][FINANCIAL RISK]")
    elif financial_risk == FINANCIAL_RISK_UNKNOWN and not ALLOW_UNKNOWN_FINANCIAL_RISK_IN_TOP:
        manual_reasons.append("FINANCIAL_RISK_UNKNOWN_MANUAL_CHECK")
    elif financial_risk == FINANCIAL_RISK_MEDIUM and not ALLOW_MEDIUM_FINANCIAL_RISK_IN_TOP:
        manual_reasons.append("FINANCIAL_RISK_MEDIUM_MANUAL_CHECK")

    # 5. Регион.
    region_status = str(
        candidate.get("region_status_override") or region.get("region") or REGION_UNKNOWN
    )
    if region_status == REGION_RUSSIA_EXCLUDED:
        add("REGION_RUSSIA_EXCLUDED", "[EXCLUDED][REGION]")
    elif region_status == REGION_RESTRICTED:
        add("REGION_RESTRICTED", "[EXCLUDED][REGION]")
    elif region_status == REGION_UNKNOWN and not ALLOW_UNKNOWN_REGION_IN_TOP:
        manual_reasons.append("REGION_UNKNOWN_MANUAL_CHECK")

    # 6. Живость репозитория/проекта.
    repo_meta = verification.get("repo_meta") or {}
    if repo_meta.get("archived") or repo_meta.get("disabled"):
        add("REPOSITORY_ARCHIVED", "[EXCLUDED][ARCHIVED_REPO]")

    # 7. Тип задачи: нетехнические задачи не смешиваются с агентскими.
    human_markers = [str(marker) for marker in task.get("human_markers") or []]
    agent_access = str(candidate.get("agent_access") or "").strip().upper()
    human_only = bool(human_markers) or agent_access == "HUMAN_ONLY"
    tech_stack = [str(skill) for skill in task.get("tech_stack") or []]
    if not human_only and not tech_stack:
        manual_reasons.append("TECH_STACK_UNRECOGNIZED_MANUAL_CHECK")

    if verified_status == BOUNTY_VERIFIED_OPEN:
        status, bounty_status = STATUS_OPEN, BOUNTY_AVAILABLE
    elif verified_status == BOUNTY_CLAIMED:
        status, bounty_status = STATUS_OPEN, BOUNTY_CLAIMED
    elif verified_status in (BOUNTY_ASSIGNED, BOUNTY_PR_LINKED):
        status, bounty_status = STATUS_OPEN, BOUNTY_TAKEN
    elif verified_status == BOUNTY_CLOSED:
        status, bounty_status = STATUS_CLOSED, BOUNTY_STATUS_UNKNOWN
    else:
        status, bounty_status = STATUS_UNKNOWN, BOUNTY_STATUS_UNKNOWN

    notes: list[str] = []
    if short_text_note:
        notes.append(short_text_note)
    if human_markers:
        notes.append(f"non-technical task markers: {human_markers}")
    if risk.get("mitigations"):
        notes.append(f"allowed modes found: {list(risk['mitigations'])[:3]}")

    return {
        "status": status,
        "bounty_status": bounty_status,
        "financial_risk": financial_risk,
        "reward_amount": reward.get("reward_amount"),
        "reward_currency": str(reward.get("reward_currency") or ""),
        "payment_type": str(reward.get("payment_type") or ""),
        "region": region_status,
        "difficulty": str(task.get("difficulty") or "UNKNOWN"),
        "estimated_time": str(task.get("estimated_time") or "UNKNOWN"),
        "tech_stack": tech_stack,
        "tech_priority": int(task.get("tech_priority") or 99),
        "beginner_friendly": bool(task.get("beginner_friendly")),
        "human_only": human_only,
        "human_only_tag": "[EXCLUDED][HUMAN_ONLY]" if human_only else "",
        "secondary": bool(str(task.get("difficulty")) == "HARD"),
        "agent_compatible": bool(not exclusions and not manual_reasons and not human_only),
        "exclusion_reasons": exclusions,
        "exclusion_tag": exclusion_tag,
        "manual_check_reasons": manual_reasons,
        "financial_risk_reasons": list(risk.get("risk_reasons") or [])[:8],
        "region_reasons": list(region.get("reasons") or []),
        "notes": notes,
        "verified_status": verified_status,
        "reward_reason": str(reward.get("reason") or ""),
        "candidate_url": str(candidate.get("url") or ""),
    }
