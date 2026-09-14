"""Финансовый риск: задания, требующие реальной финансовой активности.

Ключевое правило: если для ОБЯЗАТЕЛЬНОГО требования нужна реальная
mainnet-финансовая активность (трейдинг, свапы, депозит, покупка токенов,
оплата gas своими средствами) — задание жёстко исключается, даже если рядом
указано «Sponsored Free Lane», «Free Lane», «sponsor pays gas», credits или
free trial. Разрешены только testnet/devnet/sandbox/mock/simulated/paper/
faucet/local blockchain/free API sandbox.
"""
from __future__ import annotations

import re
from typing import Any, Final

#: Виды флагов риска.
RISK_FLAG_ORDER: Final[tuple[str, ...]] = (
    "requires_real_mainnet_activity",
    "requires_real_trade",
    "requires_deposit",
    "requires_token_purchase",
    "requires_user_gas",
    "requires_own_money",
)

#: (флаг, метка, regex, вид правила). ``kind``: imperative/descriptive.
FINANCIAL_RISK_PATTERNS: Final[tuple[tuple[str, str, str, str], ...]] = (
    # --- реальная торговля / mainnet ---
    ("requires_real_trade", "qualifying trades", r"\bqualifying trades?\b", "imperative"),
    (
        "requires_real_trade",
        "complete N trades",
        r"\b(?:complete|execute|make|perform|place|do)\b[^.]{0,60}\b(?:at least\s+)?\d+\b[^.]{0,25}\btrades?\b",
        "imperative",
    ),
    (
        "requires_real_mainnet_activity",
        "trades on mainnet",
        r"\btrades?\b[^.]{0,50}\b(?:on|via|through|using)\b[^.]{0,40}\bmainnet\b"
        r"|\bmainnet\b[^.]{0,50}\btrades?\b",
        "imperative",
    ),
    (
        "requires_real_mainnet_activity",
        "mainnet activity",
        r"\bmainnet (?:trade|trades|trading|transaction|transactions|activity|swap|swaps|order|orders)\b",
        "imperative",
    ),
    ("requires_real_trade", "real trade", r"\breal (?:trade|trades|trading)\b", "imperative"),
    (
        "requires_real_mainnet_activity",
        "on-chain trade",
        r"\bon-?chain (?:trade|trades|trading|transaction|transactions|swap|swaps|order|orders)\b",
        "imperative",
    ),
    (
        "requires_real_trade",
        "execute trades",
        r"\bexecute\b[^.]{0,30}\b(?:trades?|orders?|swaps?)\b|\bplace\b[^.]{0,25}\borders?\b",
        "imperative",
    ),
    (
        "requires_real_trade",
        "swap tokens",
        r"\b(?:swap|swaps|swap tokens?|jupiter swaps?)\b[^.]{0,40}\b(?:usdc|usdt|sol|tokens?|assets?)\b"
        r"|\bjupiter swaps?\b",
        "imperative",
    ),
    (
        "requires_real_trade",
        "open/close positions",
        r"\b(?:open|close|manage|hold)\b[^.]{0,25}\bpositions?\b",
        "descriptive",
    ),
    (
        "requires_real_trade",
        "perps/perpetuals",
        r"\bperps?\b|\bperpetual (?:futures|markets?|contracts?|swaps?|trading)\b",
        "descriptive",
    ),
    (
        "requires_real_trade",
        "trading competition",
        r"\btrading (?:competition|league|contest|challenge)\b",
        "descriptive",
    ),
    (
        "requires_real_mainnet_activity",
        "trading volume/activity",
        r"\btrading (?:volume|activity)\b|\bminimum volume\b|\btrade volume\b",
        "descriptive",
    ),
    ("requires_real_trade", "pnl tracking", r"\b(?:pnl|p&l|profit and loss)\b", "descriptive"),
    ("requires_real_trade", "actively trade", r"\bactively trade\b", "imperative"),
    (
        "requires_real_trade",
        "trade to qualify",
        r"\btrade\b[^.]{0,40}\bto (?:earn|qualify|climb|win|get|receive|increase|unlock)\b",
        "imperative",
    ),
    # --- деньги исполнителя ---
    ("requires_deposit", "deposit", r"\bdeposits?\b|\bdepositing\b|\bmake a deposit\b", "imperative"),
    (
        "requires_deposit",
        "top-up",
        r"\btop[\s\-]?ups?\b|\brecharge\b|\badd funds\b|\bfund your (?:account|wallet|balance)\b",
        "imperative",
    ),
    (
        "requires_token_purchase",
        "buy tokens",
        r"\b(?:buy|purchase|acquire|mint)\b[^.]{0,60}\b(?:tokens?|usdc|usdt|sol|nfts?|crypto|coins?)\b",
        "imperative",
    ),
    (
        "requires_own_money",
        "own funds",
        r"\byour own (?:funds|money|capital|usdc|usdt|sol|eth|wallet|balance)\b"
        r"|\bown (?:funds|money|capital)\b|\buse your funds\b|\bwith your funds\b"
        r"|\bat your own (?:cost|expense)\b|\bfrom your own (?:wallet|balance)\b",
        "imperative",
    ),
    (
        "requires_user_gas",
        "user pays gas",
        r"\bpay (?:for )?gas\b|\bcover (?:the )?gas\b|\byour own gas\b"
        r"|\bpay (?:the )?(?:gas|transaction|network) fees?\b",
        "imperative",
    ),
    (
        "requires_user_gas",
        "fees mentioned",
        r"\bgas fees?\b|\btransaction fees?\b|\bnetwork fees?\b",
        "descriptive",
    ),
    (
        "requires_own_money",
        "minimum balance",
        r"\bminimum (?:balance|deposit)\b"
        r"|\bhold\b[^.]{0,60}\b(?:at least\s+)?\$?\s?\d[\d,.]*\b[^.]{0,40}\b(?:worth|usdc|usdt|sol)\b",
        "descriptive",
    ),
)
#: Флаги, которые представляют реальную mainnet-активность.
MAINNET_FLAGS: Final[tuple[str, ...]] = ("requires_real_mainnet_activity", "requires_real_trade")
#: Код причины исключения по финансовым правилам.
REAL_ACTIVITY_EXCLUSION: Final[str] = "REAL_FINANCIAL_ACTIVITY_REQUIRED"
#: Разрешённые режимы (снимают требование реальных денег и реальной торговли).
ALLOWED_MODE_MARKERS: Final[tuple[str, ...]] = (
    "testnet",
    "test net",
    "devnet",
    "sandbox",
    "mock",
    "simulat",
    "paper trad",
    "faucet",
    "test tokens",
    "test-tokens",
    "fake tokens",
    "dummy tokens",
    "local blockchain",
    "local validator",
    "localnet",
    "free api sandbox",
    "without real funds",
    "no real money",
    "no real funds",
    "play money",
)
#: Слова-требования: если они есть рядом, трата денег/торговля обязательны.
RISK_REQUIREMENT_MARKERS: Final[tuple[str, ...]] = (
    "must",
    "required",
    "require",
    "need to",
    "needs to",
    "have to",
    "should",
    "obligated",
    "ensure you",
    "at least",
    "to participate",
    "to qualify",
    "to join",
    "to be eligible",
    "in order to",
    "in exchange",
    "you will need",
    "complete",
    "completing",
    "submit",
    "minimum requirements",
    "eligibility",
    "responsibilit",
    "deliverable",
    "you will",
    "partner will",
    "will document",
    "will participate",
    "will trade",
)
#: Признаки описания продукта/возможностей (НЕ требование к исполнителю).
PRODUCT_CONTEXT_MARKERS: Final[tuple[str, ...]] = (
    "users can",
    "user can",
    "users to",
    "enabling users",
    "enables users",
    "allows users",
    "lets users",
    "let users",
    "you can",
    "lets you",
    "allows you",
    "supporting",
    "offering",
    "offers",
    "features",
    "such as",
    "comes with",
    "come with",
    "built on",
    "tools for",
    "access to",
    "available through",
    "through the app",
    "through the platform",
    "how users",
    "users deposit",
    "users buy",
    "users fund",
)
#: Требование относится к создаваемому продукту («приложение должно позволять
#: пользователям…»), а не к исполнителю. Тогда деньги исполнителя не нужны.
PRODUCT_CAPABILITY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\b(?:app|application|tool|platform|agent|integration|solution|dapp|website|dashboard|"
        r"contract|program|api|sdk)\b[^.]{0,80}\b(?:allow|allows|enable|enables|support|supports|let|lets)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:allow|allows|enable|enables|support|supports|let|lets)\b[^.]{0,40}\b(?:users?|player|"
        r"customer|visitor)\b",
        re.I,
    ),
)
#: Маркеры, которые НЕ отменяют hard exclusion по реальной торговле.
#: (Sponsored Free Lane / credits / free trial и т.п. не делают mainnet-трейдинг безопасным.)
NON_OVERRIDING_MARKERS: Final[tuple[str, ...]] = (
    "sponsored",
    "free lane",
    "sponsored free lane",
    "sponsor pays gas",
    "gasless",
    "credits",
    "free trial",
)
#: Если рядом сказано, что gas оплачивает спонсор, флаг user_gas снимается.
GAS_COVERED_MARKERS: Final[tuple[str, ...]] = (
    "sponsor pays gas",
    "gas is sponsored",
    "gas fees are covered",
    "gasless",
    "sponsored gas",
    "we cover gas",
    "gas covered",
)

FINANCIAL_RISK_LOW: Final[str] = "LOW"
FINANCIAL_RISK_MEDIUM: Final[str] = "MEDIUM"
FINANCIAL_RISK_HIGH: Final[str] = "HIGH"


def is_product_capability_sentence(sentence: str) -> bool:
    """Проверить, что требование относится к продукту, а не к исполнителю."""
    return any(pattern.search(sentence) for pattern in PRODUCT_CAPABILITY_PATTERNS)


def risk_sentences(text: str) -> list[str]:
    """Разбить текст карточки на предложения/строки для анализа риска."""
    parts = re.split(r"(?<=[.!?;])\s+|\n+", text or "")
    return [" ".join(part.split()) for part in parts if part.strip()]


def find_allowed_mode(sentence: str) -> str:
    """Найти разрешённый режим (testnet/sandbox/simulated/faucet/local blockchain)."""
    lowered = sentence.lower()
    for marker in ALLOWED_MODE_MARKERS:
        if marker in lowered:
            return marker
    return ""


def analyze_financial_risk(
    description: str, requirements: str = "", eligibility: str = ""
) -> dict[str, Any]:
    """Определить, требует ли задание РЕАЛЬНОЙ финансовой активности.

    Ключевое правило: если обязательное требование подразумевает реальную
    mainnet-финансовую активность (mainnet-трейдинг, свапы, perps, депозит,
    покупка токенов, оплата gas своими средствами, использование своих
    USDC/USDT/SOL) — задание жёстко исключается. Наличие «Sponsored Free Lane»,
    «Free Lane», «sponsor pays gas», credits или free trial **не отменяет**
    исключение, если требуется реальная торговля.

    Разрешённые режимы (testnet/devnet/sandbox/mock/simulated/paper trading,
    faucet/test tokens, local blockchain, free API sandbox) дают ``LOW`` и
    ``requires_own_money = false``.

    Упоминание «trade»/«trading» само по себе не является триггером: нужна явная
    формулировка (qualifying trades, execute trades, swap tokens, открытие или
    закрытие позиций, perps, trading competition, PnL при обязательной торговле).

    :param description: полный текст описания карточки.
    :param requirements: текст блока требований карточки (может быть пустым).
    :param eligibility: текст eligibility-вопросов (обязательные требования).
    :returns: словарь с флагами (``requires_real_mainnet_activity``,
        ``requires_real_trade``, ``requires_deposit``, ``requires_token_purchase``,
        ``requires_user_gas``, ``requires_own_money``), ``financial_risk``,
        ``risk_reasons``, ``hard_exclusion`` и ``exclusion_reason``.
    """
    sources: tuple[tuple[str, str], ...] = (
        ("description", description),
        ("requirements", requirements),
        ("eligibility", eligibility),
    )

    flags: dict[str, list[str]] = {flag: [] for flag in RISK_FLAG_ORDER}
    risk_reasons: list[str] = []
    context_notes: list[str] = []
    mitigations: list[str] = []
    non_overriding: list[str] = []
    for source_name, text in sources:
        for sentence in risk_sentences(text):
            lowered = sentence.lower()
            allowed_mode = find_allowed_mode(sentence)
            if allowed_mode:
                mitigations.append(f"allowed mode {allowed_mode!r} in {source_name}")
            if any(marker in lowered for marker in NON_OVERRIDING_MARKERS):
                non_overriding.append(f"{source_name}: {sentence[:120]}")
            gas_covered = any(marker in lowered for marker in GAS_COVERED_MARKERS)
            trade_word = any(
                word in lowered
                for word in ("trade", "trades", "trading", "swap", "swaps", "transaction", "order", "position")
            )
            mainnet_signal = (
                "mainnet" in lowered
                or "real trade" in lowered
                or "real trading" in lowered
                or "real trades" in lowered
                or (("on-chain" in lowered or "onchain" in lowered) and trade_word)
            )

            for flag, label, pattern, kind in FINANCIAL_RISK_PATTERNS:
                if not re.search(pattern, lowered):
                    continue

                if flag == "requires_user_gas" and gas_covered:
                    mitigations.append(f"gas covered by sponsor in {source_name}")
                    continue
                if allowed_mode and not mainnet_signal:
                    # например «perform simulated trades on testnet»
                    mitigations.append(f"{label} allowed in {allowed_mode!r} mode")
                    continue

                mandatory = False
                requirement_signal = any(
                    marker in lowered for marker in RISK_REQUIREMENT_MARKERS
                )
                context_signal = any(marker in lowered for marker in PRODUCT_CONTEXT_MARKERS)
                capability_signal = is_product_capability_sentence(lowered)
                if capability_signal:
                    mandatory = False
                elif mainnet_signal:
                    mandatory = True
                elif source_name in ("eligibility", "requirements") or requirement_signal:
                    mandatory = True
                elif context_signal:
                    mandatory = False
                elif kind == "imperative":
                    mandatory = True

                if mandatory:
                    flags[flag].append(label)
                    risk_reasons.append(f'{flag}: {label} -> "{sentence[:150]}"')
                else:
                    context_notes.append(
                        f'{label} (context only) in {source_name}: "{sentence[:150]}"'
                    )

    requires_real_mainnet_activity = bool(flags["requires_real_mainnet_activity"])
    requires_real_trade = bool(flags["requires_real_trade"] or requires_real_mainnet_activity)
    requires_deposit = bool(flags["requires_deposit"])
    requires_token_purchase = bool(flags["requires_token_purchase"])
    requires_user_gas = bool(flags["requires_user_gas"])
    requires_own_money = bool(flags["requires_own_money"])

    hard_exclusion = any(
        (
            requires_real_mainnet_activity,
            requires_real_trade,
            requires_deposit,
            requires_token_purchase,
            requires_user_gas,
            requires_own_money,
        )
    )

    if hard_exclusion:
        financial_risk = FINANCIAL_RISK_HIGH
    elif context_notes:
        financial_risk = FINANCIAL_RISK_MEDIUM
    else:
        financial_risk = FINANCIAL_RISK_LOW

    if not risk_reasons and financial_risk == FINANCIAL_RISK_MEDIUM:
        risk_reasons.extend(sorted(set(context_notes))[:4])
    if financial_risk == FINANCIAL_RISK_LOW:
        risk_reasons.append("no real-money or real-trading requirements found in card text")

    return {
        "financial_risk": financial_risk,
        "requires_real_mainnet_activity": requires_real_mainnet_activity,
        "requires_real_trade": requires_real_trade,
        "requires_deposit": requires_deposit,
        "requires_token_purchase": requires_token_purchase,
        "requires_user_gas": requires_user_gas,
        "requires_own_money": requires_own_money,
        "risk_reasons": risk_reasons[:12],
        "reasons": risk_reasons[:12],
        "hard_exclusion": hard_exclusion,
        "exclusion_reason": REAL_ACTIVITY_EXCLUSION if hard_exclusion else "",
        "mitigations": sorted(set(mitigations))[:8],
        "context_notes": sorted(set(context_notes))[:8],
        "non_overriding_notes": sorted(set(non_overriding))[:5],
        "own_money_hits": sorted(set(flags["requires_own_money"] + flags["requires_deposit"])),
        "trade_hits": sorted(set(flags["requires_real_trade"])),
    }
