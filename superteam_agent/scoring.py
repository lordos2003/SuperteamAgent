"""Deterministic-скоринг заданий (внешний AI не используется).

Формула: ``reward_score + agent_score + tech_score + difficulty_score +
competition_score + time_score - risk_penalty - region_penalty -
nontech_penalty - protocol_penalty``.

В итоговый список кандидатов попадает только ``VERIFIED_OPEN`` с
подтверждённым будущим дедлайном; ``requires_own_money=true``,
``financial_risk=HIGH``, объявленные winners и несовместимый регион дают
жёсткий ``EXCLUDE``.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Final, Mapping

from .card import parse_utc
from .config import (
    FINANCIAL_STATE_CONFIRMED_SAFE,
    FINANCIAL_STATE_RISK_DETECTED,
    FINANCIAL_STATE_UNKNOWN,
    MIN_TEXT_FOR_FINANCIAL_LOW,
    UNKNOWN,
    VERIFIED_HUMAN_ONLY,
    VERIFIED_OPEN,
)
from .risk import (
    FINANCIAL_RISK_MEDIUM,
    REAL_ACTIVITY_EXCLUSION,
    analyze_financial_risk,
)

#: Rewards: приоритет крипто-выплат (фактическая валюта, не слово «crypto»).
REWARD_CURRENCY_SCORES: Final[dict[str, int]] = {
    "USDC": 35,
    "USDT": 35,
    "SOL": 30,
    "JUPUSD": 25,
    "USDG": 20,
}
#: Прочие крипто/стейблкоины.
DEFAULT_CRYPTO_REWARD_SCORE: Final[int] = 15
#: Фиатные валюты (никакого приоритета).
FIAT_CURRENCIES: Final[tuple[str, ...]] = ("USD", "EUR", "GBP", "UAH", "TRY", "NGN", "INR", "JPY", "BRL")
#: Известные крипто-токены (для определения reward_type).
KNOWN_CRYPTO_CURRENCIES: Final[tuple[str, ...]] = (
    "USDC", "USDT", "SOL", "JUPUSD", "USDG", "USDS", "PYUSD", "USDE", "USDT0", "BONK", "JUP",
    "RAY", "MNDE", "ORCA", "WIF", "PYTH", "SHDW", "TNSR", "DRIFT", "IO", "META", "ETH", "BTC",
)
#: Монеты, которые нужно сравнивать без учёта регистра (jupUSD и т.п.).
REWARD_CURRENCY_ALIASES: Final[dict[str, str]] = {
    "JUPUSD": "jupUSD",
}

#: Agent access: главный фактор для наших задач.
AGENT_ACCESS_SCORES: Final[dict[str, int]] = {
    "AGENT_ONLY": 30,
    "AGENT_ALLOWED": 20,
    "UNKNOWN": 0,
    "HUMAN_ONLY": -100,
}
AGENT_ACCESS_VALUES: Final[tuple[str, ...]] = ("AGENT_ONLY", "AGENT_ALLOWED", "HUMAN_ONLY", "UNKNOWN")

#: Стек и типы работ (учитываются все найденные навыки, суммы складываются).
STACK_KEYWORDS: Final[tuple[tuple[str, tuple[str, ...], int], ...]] = (
    ("python", ("python", "django", "flask", "fastapi", "pandas", "beautifulsoup"), 15),
    ("playwright", ("playwright", "puppeteer", "browser automation"), 15),
    ("web scraping", ("scraping", "scraper", "scrape", "crawler", "crawl", "parsing", "parser"), 15),
    ("automation", ("automation", "automate", "automated", "bot", "workflow script"), 12),
    ("javascript", ("javascript", "typescript", "node.js", "nodejs", "react", "next.js", "nextjs", "vue", "svelte"), 12),
    ("testing/QA", ("testing", "qa", "unit test", "e2e", "test cases", "bug fix", "bugfix", "bug report"), 12),
    ("api", ("api", "rest", "graphql", "webhook", "integration", "endpoint", "sdk"), 10),
    ("csv/excel", ("csv", "excel", "spreadsheet", "google sheets", "xlsx"), 10),
    ("html/css", ("html", "css", "tailwind", "landing page", "frontend", "web app"), 10),
    ("backend", ("backend", "back-end", "server-side", "database", "postgres", "sql", "supabase", "firebase"), 8),
    ("frontend", ("frontend", "front-end", "ui component", "dashboard ui"), 6),
)
#: Максимум, который может дать tech_score (чтобы смешанные задачи не раздували балл).
TECH_SCORE_CAP: Final[int] = 45
#: Штраф за Solana/Rust protocol development (не запрет, только для beginner-профиля).
PROTOCOL_PENALTY: Final[int] = -10
PROTOCOL_KEYWORDS: Final[tuple[str, ...]] = (
    "rust",
    "anchor",
    "on-chain program",
    "onchain program",
    "solana program",
    "smart contract",
    "cpi",
    "spl token",
    "program development",
    "validator client",
)
#: Нетехнические задания: не запрещены, но не должны попадать в топ разработческих.
NONTECH_PENALTIES: Final[tuple[tuple[str, tuple[str, ...], int], ...]] = (
    (
        "design",
        ("design", "designer", "ui/ux", "uiux", "figma", "graphic", "logo", "poster", "banner",
         "illustration", "merch", "brand"),
        -15,
    ),
    (
        "content",
        ("content", "article", "blog", "thread", "tweet", "x post", "video", "meme", "newsletter",
         "podcast", "translation", "copywriting"),
        -15,
    ),
    (
        "marketing",
        ("marketing", "growth", "ambassador", "referral", "social media", "community manager",
         "engagement", "shill"),
        -20,
    ),
)

#: Сложность: beginner-friendly поощряется.
DIFFICULTY_SCORES: Final[dict[str, int]] = {
    "EASY": 20,
    "MEDIUM": 5,
    "HARD": -20,
    "UNKNOWN": 0,
}
#: Признаки EASY-задач (beginner friendliness).
BEGINNER_KEYWORDS: Final[tuple[str, ...]] = (
    "quick",
    "simple",
    "easy",
    "straightforward",
    "beginner",
    "beginners",
    "no experience",
    "bug fix",
    "qa",
    "testing",
    "documentation",
    "small automation",
    "scraping",
    "api integration",
    "step by step",
    "step-by-step",
)
#: Признаки HARD-задач.
HARD_KEYWORDS: Final[tuple[str, ...]] = (
    "rust",
    "anchor",
    "on-chain program",
    "smart contract",
    "zero-knowledge",
    "zk-proof",
    "zk proof",
    "cryptography",
    "consensus",
    "light client",
    "compiler",
    "kernel",
)

#: Конкуренция (количество submissions).
COMPETITION_RULES: Final[tuple[tuple[int, int, int], ...]] = (
    (0, 10, 10),
    (11, 30, 5),
    (31, 100, 0),
)
COMPETITION_HIGH_PENALTY: Final[int] = -10
COMPETITION_HIGH_THRESHOLD: Final[int] = 100

#: Время до дедлайна (часы, нижняя граница включительно).
TIME_RULES: Final[tuple[tuple[float, int, str], ...]] = (
    (168.0, 0, "> 7 days left"),
    (72.0, -5, "3-7 days left"),
    (24.0, -10, "1-3 days left"),
    (0.0, -20, "< 24h left"),
)

#: Финансовый риск MEDIUM: не исключаем, но сильно понижаем ranking.
MEDIUM_RISK_PENALTY: Final[int] = -25
#: Региональное ограничение, которое нельзя проверить без данных пользователя.
REGION_RESTRICTED_PENALTY: Final[int] = -15

#: Пороговые значения итогового score для метки priority.
PRIORITY_HIGH_THRESHOLD: Final[int] = 60
PRIORITY_MEDIUM_THRESHOLD: Final[int] = 35

#: Метка «Estimated fit» (детерминированно от score).
ESTIMATED_FIT_RULES: Final[tuple[tuple[int, str], ...]] = (
    (70, "EXCELLENT"),
    (45, "GOOD"),
    (20, "FAIR"),
    (0, "WEAK"),
)

#: Регион: значения, которые не являются ограничением.
GLOBAL_REGION_VALUES: Final[tuple[str, ...]] = (
    "",
    "global",
    "worldwide",
    "anywhere",
    "remote",
    "all countries",
    "any country",
)
#: Переменные окружения с регионом пользователя (через запятую), например:
#: ``$env:SUPERTEAM_USER_REGION="Ukraine, Europe"``.
USER_REGION_ENVS: Final[tuple[str, ...]] = ("SUPERTEAM_USER_REGION", "SUPERTEAM_USER_COUNTRY")
#: Явные региональные ограничения в тексте карточки.
REGION_RESTRICTION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"only open for (?:people|users|members|residents|builders|creators|traders|teams)"
        r"(?: in| from| based in)? ([A-Za-z][A-Za-z .,'\-]{2,40})",
        re.I,
    ),
    re.compile(r"restricted to ([A-Za-z][A-Za-z .,'\-]{2,40})", re.I),
    re.compile(r"\b([A-Z][A-Za-z]+(?:\s+(?:and\s+)?[A-Z][A-Za-z]+){0,2})\s+only\b"),
)
REGION_SPLIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s*(?:,|/|&|\band\b)\s*")
REGION_TRAILING_WORDS: Final[tuple[str, ...]] = (
    "audience", "users", "people", "based", "citizens", "residents", "nationals", "only",
)
#: Слова, из-за которых кандидат в регион считается мусором.
REGION_STOPWORDS: Final[tuple[str, ...]] = (
    "listing", "bounty", "task", "challenge", "program", "programme", "regional", "this", "that",
    "app", "platform", "people", "users", "members", "residents", "builders", "creators",
    "traders", "teams", "audience", "in", "from", "to", "for", "and", "or", "is", "it", "the",
)


def listing_text(entry: Mapping[str, Any]) -> str:
    """Собрать весь текст задания для анализа (title, description, rewards, region)."""
    parts = [
        str(entry.get(key) or "")
        for key in ("title", "description", "rewards", "region_text", "type", "region")
    ]
    return " ".join(part for part in parts if part)


def normalize_agent_access(value: Any) -> str:
    """Нормализовать agent access: AGENT_ONLY / AGENT_ALLOWED / HUMAN_ONLY / UNKNOWN."""
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not text:
        return "UNKNOWN"
    if "AGENT_ONLY" in text:
        return "AGENT_ONLY"
    if "AGENT_ALLOWED" in text or "AGENT_ELIGIBLE" in text or "AGENT_ACCESS" in text:
        return "AGENT_ALLOWED"
    if "HUMAN" in text:
        return "HUMAN_ONLY"
    return "UNKNOWN"


def token_from_reward(text: str) -> str:
    """Вытащить тикер токена из строки reward (например «3 500 USDG» -> ``USDG``)."""
    match = re.search(r"([A-Z][A-Z0-9$]{1,11})\s*$", (text or "").strip())
    return match.group(1) if match else ""


def reward_info(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Определить фактическую валюту reward и её тип (без «магии» слова crypto).

    :param entry: запись с полями ``reward_amount``, ``token``, ``reward``.
    :returns: словарь ``{"reward_amount", "reward_currency", "reward_type",
        "reward_score", "reason"}``; при неопределимой валюте — ``UNKNOWN``.
    """
    amount = entry.get("reward_amount")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        amount = None

    currency_raw = str(entry.get("token") or "").strip()
    if not currency_raw:
        currency_raw = token_from_reward(str(entry.get("reward") or ""))
    currency_upper = currency_raw.upper()

    if currency_upper in REWARD_CURRENCY_SCORES:
        reward_type = "crypto"
        score = REWARD_CURRENCY_SCORES[currency_upper]
    elif currency_upper in FIAT_CURRENCIES:
        reward_type = "fiat"
        score = 0
    elif currency_upper in KNOWN_CRYPTO_CURRENCIES:
        reward_type = "crypto"
        score = DEFAULT_CRYPTO_REWARD_SCORE
    elif currency_upper and re.fullmatch(r"[A-Z0-9$]{2,12}", currency_upper):
        reward_type = "crypto (unverified)"
        score = DEFAULT_CRYPTO_REWARD_SCORE
    else:
        reward_type = "UNKNOWN"
        score = 0

    currency = REWARD_CURRENCY_ALIASES.get(currency_upper, currency_raw) or "UNKNOWN"
    return {
        "reward_amount": amount,
        "reward_currency": currency,
        "reward_type": reward_type,
        "reward_score": score,
        "reason": f"reward currency {currency} ({reward_type}) -> {score:+d}",
    }


def detect_skills(text: str) -> dict[str, Any]:
    """Найти технические навыки задания и посчитать tech_score.

    Учитываются все найденные направления (смешанные задачи суммируются),
    итог ограничен ``TECH_SCORE_CAP``.
    """
    lowered = text.lower()
    skills: list[str] = []
    raw_score = 0
    reasons: list[str] = []
    for label, keywords, points in STACK_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            skills.append(label)
            raw_score += points
            reasons.append(f"{label} (+{points})")

    score = min(raw_score, TECH_SCORE_CAP)
    if raw_score > TECH_SCORE_CAP:
        reasons.append(f"tech cap applied ({raw_score} -> {score})")

    protocol_hits = [keyword for keyword in PROTOCOL_KEYWORDS if keyword in lowered]
    return {
        "skills": skills,
        "tech_score": score,
        "reasons": reasons,
        "protocol_hits": protocol_hits[:6],
    }


def estimate_difficulty(text: str) -> dict[str, Any]:
    """Определить сложность задания: EASY / MEDIUM / HARD / UNKNOWN."""
    lowered = text.lower()
    easy_hits = [keyword for keyword in BEGINNER_KEYWORDS if keyword in lowered]
    hard_hits = [keyword for keyword in HARD_KEYWORDS if keyword in lowered]

    if hard_hits:
        difficulty = "HARD"
    elif easy_hits:
        difficulty = "EASY"
    elif lowered.strip():
        difficulty = "MEDIUM"
    else:
        difficulty = "UNKNOWN"

    indicators = [f"easy: {keyword}" for keyword in easy_hits[:5]]
    indicators += [f"hard: {keyword}" for keyword in hard_hits[:5]]
    return {
        "difficulty": difficulty,
        "difficulty_score": DIFFICULTY_SCORES[difficulty],
        "indicators": indicators,
        "reason": f"difficulty {difficulty} -> {DIFFICULTY_SCORES[difficulty]:+d}",
    }


def time_info(deadline_moment: datetime | None, now: datetime) -> dict[str, Any]:
    """Посчитать часы до дедлайна и time_score (это ranking, а не фильтр)."""
    if deadline_moment is None:
        return {
            "hours_until_deadline": None,
            "time_score": 0,
            "reason": "deadline not confirmed on card (time score 0)",
        }

    hours = (deadline_moment - now).total_seconds() / 3600.0
    for threshold, score, label in TIME_RULES:
        if hours >= threshold:
            return {
                "hours_until_deadline": round(hours, 1),
                "time_score": score,
                "reason": f"{label} ({hours:.1f}h) -> {score:+d}",
            }
    return {
        "hours_until_deadline": round(hours, 1),
        "time_score": -20,
        "reason": f"deadline already passed ({hours:.1f}h) -> -20",
    }


def competition_info(submissions: int | None) -> dict[str, Any]:
    """Оценить конкуренцию по количеству submissions с карточки."""
    if submissions is None:
        return {
            "submissions": None,
            "competition_score": 0,
            "reason": "submissions count unavailable on card -> 0",
        }
    if submissions > COMPETITION_HIGH_THRESHOLD:
        return {
            "submissions": submissions,
            "competition_score": COMPETITION_HIGH_PENALTY,
            "reason": f"{submissions} submissions (>100) -> {COMPETITION_HIGH_PENALTY:+d}",
        }
    for low, high, score in COMPETITION_RULES:
        if low <= submissions <= high:
            return {
                "submissions": submissions,
                "competition_score": score,
                "reason": f"{submissions} submissions ({low}-{high}) -> {score:+d}",
            }
    return {
        "submissions": submissions,
        "competition_score": 0,
        "reason": f"{submissions} submissions -> 0",
    }


def clean_region_name(value: str) -> str:
    """Очистить название региона от мусора вида «Thailand and African audience»."""
    text = " ".join(str(value or "").split()).strip(" .,;:-")
    words = [word for word in text.split() if word.lower().strip(".,") not in REGION_TRAILING_WORDS]
    return " ".join(words[:4]).strip(" .,;:-")


def is_valid_region_name(value: str) -> bool:
    """Проверить, что извлечённое название похоже на регион, а не на служебную фразу."""
    if not value or len(value) < 3:
        return False
    words = value.split()
    if len(words) > 3:
        return False
    return not any(word.lower().strip(".,") in REGION_STOPWORDS for word in words)


def user_regions() -> list[str]:
    """Регионы пользователя из переменных окружения (если заданы)."""
    regions: list[str] = []
    for name in USER_REGION_ENVS:
        raw = os.getenv(name, "")
        for part in REGION_SPLIT_PATTERN.split(raw):
            cleaned = clean_region_name(part)
            if cleaned:
                regions.append(cleaned.lower())
    return regions


def region_info(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Проанализировать региональные ограничения карточки.

    Ограничением считается только явное указание страны/региона: поле ``region``
    (кроме ``Global``) или текст вида «only open for people in Thailand»,
    «restricted to Canada», «Nigeria only». Если регион пользователя неизвестен
    (переменная окружения не задана), задание **не исключается**, а получает
    ``REGION_RESTRICTED`` и штраф — решение остаётся за пользователем.

    :param entry: запись с полями ``region``, ``region_text``, ``description``.
    :returns: словарь с ``region``, ``restricted_regions``, ``eligibility_status``,
        ``region_score``, ``incompatible``, ``reasons``.
    """
    region_field = clean_region_name(str(entry.get("region") or ""))
    haystack = " ".join(
        str(entry.get(key) or "") for key in ("region_text", "description", "title")
    )

    restrictions: list[str] = []
    if region_field and region_field.lower() not in GLOBAL_REGION_VALUES:
        restrictions.append(region_field)
    for pattern in REGION_RESTRICTION_PATTERNS:
        for match in pattern.finditer(haystack):
            candidate = clean_region_name(match.group(1))
            if is_valid_region_name(candidate) and candidate.lower() not in GLOBAL_REGION_VALUES:
                restrictions.append(candidate)

    unique_restrictions = sorted({restriction for restriction in restrictions})
    display_region = region_field or (unique_restrictions[0] if unique_restrictions else "UNKNOWN")

    if not unique_restrictions:
        return {
            "region": display_region or "UNKNOWN",
            "restricted_regions": [],
            "eligibility_status": "ELIGIBLE",
            "region_score": 0,
            "incompatible": False,
            "reasons": ["no regional restriction found on card"],
        }

    known = user_regions()
    if known:
        matched = any(
            user in restriction.lower() or restriction.lower() in user
            for restriction in unique_restrictions
            for user in known
        )
        if matched:
            return {
                "region": display_region,
                "restricted_regions": unique_restrictions,
                "eligibility_status": "ELIGIBLE",
                "region_score": 0,
                "incompatible": False,
                "reasons": [
                    f"regional restriction matches your configured region: {unique_restrictions}"
                ],
            }
        return {
            "region": display_region,
            "restricted_regions": unique_restrictions,
            "eligibility_status": "REGION_RESTRICTED",
            "region_score": 0,
            "incompatible": True,
            "reasons": [
                f"card restricts to {unique_restrictions}, your configured region is {known} -> exclude"
            ],
        }

    return {
        "region": display_region,
        "restricted_regions": unique_restrictions,
        "eligibility_status": "REGION_RESTRICTED",
        "region_score": REGION_RESTRICTED_PENALTY,
        "incompatible": False,
        "reasons": [
            f"card restricts to {unique_restrictions}; set SUPERTEAM_USER_REGION to verify compatibility "
            f"({REGION_RESTRICTED_PENALTY:+d})"
        ],
    }


def estimated_fit(score: int) -> str:
    """Детерминированная метка «Estimated fit» по итоговому score."""
    for threshold, label in ESTIMATED_FIT_RULES:
        if score >= threshold:
            return label
    return "WEAK"


def score_listing(listing: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic rule-based оценка задания (внешний AI не используется).

    Формула: ``reward_score + agent_score + tech_score + difficulty_score +
    competition_score + time_score - risk_penalty - region_penalty -
    nontech_penalty - protocol_penalty``.

    В итоговый список кандидатов попадает только ``VERIFIED_OPEN`` с
    подтверждённым будущим дедлайном; ``requires_own_money=true``,
    ``financial_risk=HIGH``, объявленные winners и несовместимый регион дают
    жёсткий ``EXCLUDE``.

    :param listing: запись задания (данные карточки + источники).
    :returns: словарь со ``score``, ``score_breakdown``, ``why``, разобранными
        полями и итоговым решением ``final_decision``.
    """
    now = datetime.now(timezone.utc)
    text = listing_text(listing)

    reward = reward_info(listing)
    agent_access = normalize_agent_access(listing.get("agent_access"))
    agent_access_unknown = bool(
        listing.get("agent_access_unknown", agent_access == "UNKNOWN")
    )
    agent_score = AGENT_ACCESS_SCORES[agent_access]
    skills = detect_skills(text)
    difficulty = estimate_difficulty(text)
    region = region_info(listing)
    deadline_moment = parse_utc(listing.get("deadline"))
    time_data = time_info(deadline_moment, now)
    submissions = listing.get("submissions")
    competition = competition_info(submissions if isinstance(submissions, int) else None)

    risk = analyze_financial_risk(
        str(listing.get("description_full") or listing.get("description") or ""),
        str(listing.get("requirements_text") or ""),
        str(listing.get("eligibility_text") or ""),
    )

    lowered = text.lower()
    nontech_labels: list[str] = []
    nontech_penalty = 0
    for label, keywords, points in NONTECH_PENALTIES:
        if any(keyword in lowered for keyword in keywords):
            nontech_labels.append(label)
            nontech_penalty += points

    protocol_penalty = PROTOCOL_PENALTY if skills["protocol_hits"] else 0
    risk_penalty = MEDIUM_RISK_PENALTY if risk["financial_risk"] == FINANCIAL_RISK_MEDIUM else 0
    region_penalty = int(region.get("region_score") or 0)

    breakdown: dict[str, int] = {
        "reward_score": int(reward["reward_score"]),
        "agent_score": int(agent_score),
        "tech_score": int(skills["tech_score"]),
        "difficulty_score": int(difficulty["difficulty_score"]),
        "competition_score": int(competition["competition_score"]),
        "time_score": int(time_data["time_score"]),
        "risk_penalty": risk_penalty,
        "region_penalty": region_penalty,
        "nontech_penalty": nontech_penalty,
        "protocol_penalty": protocol_penalty,
    }
    score = sum(breakdown.values())

    why: list[str] = [str(reward["reason"])]
    why.append(f"agent access {agent_access} -> {agent_score:+d}")
    if skills["skills"]:
        why.append(f"tech: {', '.join(skills['skills'])} -> {skills['tech_score']:+d}")
    why.append(str(difficulty["reason"]))
    why.append(str(competition["reason"]))
    why.append(str(time_data["reason"]))
    if risk_penalty:
        why.append(f"financial risk MEDIUM (needs manual check) -> {risk_penalty:+d}")
    if risk["hard_exclusion"]:
        why.append(f"HARD EXCLUDE: {REAL_ACTIVITY_EXCLUSION} -> {risk['risk_reasons'][0][:120] if risk['risk_reasons'] else ''}")
    why.append(str(region["reasons"][0]))
    if nontech_labels:
        why.append(f"non-technical task ({', '.join(nontech_labels)}) -> {nontech_penalty:+d}")
    if protocol_penalty:
        why.append(f"protocol-level work (Rust/Solana) -> {protocol_penalty:+d}")

    verification_status = str(listing.get("verification_status") or UNKNOWN)
    human_only_status = verification_status == VERIFIED_HUMAN_ONLY
    human_only = bool(listing.get("human_only")) or human_only_status or agent_access == "HUMAN_ONLY"
    hard_exclusions: list[str] = []
    if verification_status != VERIFIED_OPEN and not human_only_status:
        # Любой статус, кроме подтверждённо-открытого, — жёсткое исключение.
        # VERIFIED_HUMAN_ONLY не исключается: такие задачи попадают только в
        # отдельный список human-only и никогда — в агентские.
        hard_exclusions.append(f"card verification: {verification_status}")
    if deadline_moment is None:
        hard_exclusions.append("deadline not confirmed on card")
    elif deadline_moment < now:
        hard_exclusions.append("card deadline already passed")
    if listing.get("has_winners"):
        hard_exclusions.append("winners already announced")
    if risk["hard_exclusion"]:
        hard_exclusions.append(REAL_ACTIVITY_EXCLUSION)
    if region.get("incompatible"):
        hard_exclusions.append("region restriction incompatible with your configured region")

    decision = "EXCLUDE" if hard_exclusions else "CANDIDATE"
    exclusion_reason = hard_exclusions[0] if hard_exclusions else ""

    # Состояние финансового риска: отсутствие найденных рисков — доказательство
    # безопасности только при достаточном тексте карточки.
    description_text = str(listing.get("description_full") or listing.get("description") or "")
    if risk["hard_exclusion"]:
        financial_risk_state = FINANCIAL_STATE_RISK_DETECTED
    elif risk["financial_risk"] == FINANCIAL_RISK_MEDIUM:
        financial_risk_state = FINANCIAL_STATE_UNKNOWN
    elif len(description_text.strip()) >= MIN_TEXT_FOR_FINANCIAL_LOW:
        financial_risk_state = FINANCIAL_STATE_CONFIRMED_SAFE
    else:
        financial_risk_state = FINANCIAL_STATE_UNKNOWN

    priority = (
        "HIGH"
        if score >= PRIORITY_HIGH_THRESHOLD
        else "MEDIUM"
        if score >= PRIORITY_MEDIUM_THRESHOLD
        else "LOW"
    )

    return {
        "score": score,
        "score_breakdown": breakdown,
        "why": why[:8],
        "estimated_fit": estimated_fit(score),
        # Исключённая задача не может иметь высокий приоритет, даже если её
        # «сырой» score большой (например устаревший API-listing с OPEN).
        "priority": "EXCLUDED" if hard_exclusions else priority,
        "effective_priority": "EXCLUDED" if hard_exclusions else priority,
        "reward_amount": reward["reward_amount"],
        "reward_currency": reward["reward_currency"],
        "reward_type": reward["reward_type"],
        "agent_access": agent_access,
        "agent_access_unknown": agent_access_unknown,
        "human_only": human_only,
        "skills": skills["skills"],
        "difficulty": difficulty["difficulty"],
        "difficulty_indicators": difficulty["indicators"],
        "eligibility_status": region["eligibility_status"],
        "region": region["region"],
        "restricted_regions": region["restricted_regions"],
        "region_reasons": region["reasons"],
        "hours_until_deadline": time_data["hours_until_deadline"],
        "submissions": competition["submissions"],
        "financial_risk": risk["financial_risk"],
        "financial_risk_state": financial_risk_state,
        "requires_own_money": risk["requires_own_money"],
        "requires_real_mainnet_activity": risk["requires_real_mainnet_activity"],
        "requires_real_trade": risk["requires_real_trade"],
        "requires_deposit": risk["requires_deposit"],
        "requires_token_purchase": risk["requires_token_purchase"],
        "requires_user_gas": risk["requires_user_gas"],
        "risk_reasons": risk["risk_reasons"],
        "risk_mitigations": risk["mitigations"],
        "risk_context_notes": risk["context_notes"],
        "risk_non_overriding_notes": risk["non_overriding_notes"],
        "verification_status": verification_status,
        "decision": decision,
        "exclusion_reason": exclusion_reason,
        "final_decision": decision,
        "hard_exclusion_reasons": hard_exclusions,
        "exclusion_reasons": hard_exclusions,
    }
