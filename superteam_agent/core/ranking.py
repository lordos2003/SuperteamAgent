"""Ранжирование задач: порядок приоритетов из задания.

Порядок (сначала самое важное):

1. crypto-выплата (USDC/USDT/SOL и т.п.);
2. отсутствие финансового риска (``financial_risk = LOW``);
3. подтверждённая открытость (первоисточник проверен);
4. beginner-friendly;
5. маленькая/простая задача;
6. размер награды;
7. global / Russia allowed.

Веса детерминированные (без внешнего AI) — как и в остальной части проекта.
"""
from __future__ import annotations

import math
from typing import Any, Final, Mapping, Sequence

from ..config import PAYMENT_TYPE_CRYPTO, PAYMENT_TYPE_FIAT
from ..risk import FINANCIAL_RISK_LOW
from .filters import TECH_PRIORITY
from .models import (
    BOUNTY_AVAILABLE,
    REGION_GLOBAL,
    REGION_RUSSIA_ALLOWED,
    STATUS_OPEN,
)

#: Вклад каждого критерия в итоговый балл.
RANK_WEIGHTS: Final[dict[str, float]] = {
    "crypto_reward": 40.0,
    "fiat_reward": 10.0,
    "no_financial_risk": 30.0,
    "confirmed_open": 25.0,
    "beginner_friendly": 20.0,
    "easy_task": 12.0,
    "medium_task": 6.0,
    "reward_size_cap": 25.0,
    "global_region": 10.0,
    "tech_priority": 1.0,
}
#: Максимальный вклад за размер награды (log-шкала, чтобы $10 000 не «съедал» всё).
REWARD_SIZE_MAX: Final[float] = RANK_WEIGHTS["reward_size_cap"]


def reward_size_score(amount: Any) -> float:
    """Вклад размера награды (логарифмическая шкала, ограничен сверху).

    Маленькие bounty ($1–25) не отбрасываются, но и не перевешивают
    приоритеты crypto/no-risk/open.
    """
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
        return 0.0
    return min(math.log10(float(amount)) * 5.0, REWARD_SIZE_MAX)


def ranking_factors(candidate: Mapping[str, Any]) -> list[str]:
    """Список сработавших факторов ранжирования (для аудита и вывода)."""
    factors: list[str] = []
    payment_type = str(candidate.get("payment_type") or "")
    if payment_type == PAYMENT_TYPE_CRYPTO:
        factors.append(f"crypto reward -> +{RANK_WEIGHTS['crypto_reward']:.0f}")
    elif payment_type == PAYMENT_TYPE_FIAT:
        factors.append(f"fiat reward -> +{RANK_WEIGHTS['fiat_reward']:.0f}")
    if str(candidate.get("financial_risk") or "") == FINANCIAL_RISK_LOW:
        factors.append(f"no financial risk -> +{RANK_WEIGHTS['no_financial_risk']:.0f}")
    if (
        str(candidate.get("status") or "") == STATUS_OPEN
        and str(candidate.get("bounty_status") or "") == BOUNTY_AVAILABLE
    ):
        factors.append(f"confirmed open -> +{RANK_WEIGHTS['confirmed_open']:.0f}")
    if candidate.get("beginner_friendly"):
        factors.append(f"beginner friendly -> +{RANK_WEIGHTS['beginner_friendly']:.0f}")
    difficulty = str(candidate.get("difficulty") or "")
    if difficulty == "EASY":
        factors.append(f"small/simple task -> +{RANK_WEIGHTS['easy_task']:.0f}")
    elif difficulty == "MEDIUM":
        factors.append(f"medium task -> +{RANK_WEIGHTS['medium_task']:.0f}")
    size = reward_size_score(candidate.get("reward_amount"))
    if size:
        factors.append(f"reward size {candidate.get('reward_amount')} -> +{size:.1f}")
    if str(candidate.get("region") or "") in (REGION_GLOBAL, REGION_RUSSIA_ALLOWED):
        factors.append(f"region {candidate.get('region')} -> +{RANK_WEIGHTS['global_region']:.0f}")
    priority = candidate.get("tech_priority")
    if isinstance(priority, int) and 0 <= priority < len(TECH_PRIORITY):
        factors.append(f"tech priority #{priority + 1} ({TECH_PRIORITY[priority]})")
    return factors


def rank_score(candidate: Mapping[str, Any]) -> float:
    """Итоговый балл ранжирования (детерминированный)."""
    score = 0.0
    payment_type = str(candidate.get("payment_type") or "")
    if payment_type == PAYMENT_TYPE_CRYPTO:
        score += RANK_WEIGHTS["crypto_reward"]
    elif payment_type == PAYMENT_TYPE_FIAT:
        score += RANK_WEIGHTS["fiat_reward"]
    if str(candidate.get("financial_risk") or "") == FINANCIAL_RISK_LOW:
        score += RANK_WEIGHTS["no_financial_risk"]
    if (
        str(candidate.get("status") or "") == STATUS_OPEN
        and str(candidate.get("bounty_status") or "") == BOUNTY_AVAILABLE
    ):
        score += RANK_WEIGHTS["confirmed_open"]
    if candidate.get("beginner_friendly"):
        score += RANK_WEIGHTS["beginner_friendly"]
    difficulty = str(candidate.get("difficulty") or "")
    if difficulty == "EASY":
        score += RANK_WEIGHTS["easy_task"]
    elif difficulty == "MEDIUM":
        score += RANK_WEIGHTS["medium_task"]
    score += reward_size_score(candidate.get("reward_amount"))
    if str(candidate.get("region") or "") in (REGION_GLOBAL, REGION_RUSSIA_ALLOWED):
        score += RANK_WEIGHTS["global_region"]
    priority = candidate.get("tech_priority")
    if isinstance(priority, int) and 0 <= priority < len(TECH_PRIORITY):
        score += (len(TECH_PRIORITY) - priority) * RANK_WEIGHTS["tech_priority"]
    return round(score, 3)


def sort_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Отсортировать задачи по баллу, затем по названию (стабильный порядок).

    Если ``rank_score`` в записи отсутствует (например, запись собрана вне
    :func:`superteam_agent.sources.base.finalize_candidate`), балл считается на
    месте — иначе сортировка молча деградировала бы до нулей.
    """

    def key(item: Mapping[str, Any]) -> tuple[float, str]:
        stored = item.get("rank_score")
        score = float(stored) if isinstance(stored, (int, float)) else rank_score(item)
        return -score, str(item.get("title") or "").lower()

    return sorted(candidates, key=key)
