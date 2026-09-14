# SuperteamAgent

Мини-проект на Python для работы с официальным **Superteam Earn Agent API**.

* Этап 1 — надёжное authenticated подключение и получение живых заданий (live listings).
* Этап 2 — проверка актуальности каждого задания по публичной карточке
  `https://superteam.fun/earn/listing/{slug}` (обычный HTTP GET, без Playwright).
* Этап 3 — гибридный поиск: Agent API + публичная лента сайта + проверка карточек,
  фильтр актуальности, финансовый риск и приоритеты.
* Этап 4 — intelligent filtering + ranking: детерминированный rule-based скоринг
  (reward, agent access, стек, сложность, конкуренция, время), TOP-разделы и
  отдельные списки agent-compatible / human-only.

Скрипт один раз читает API key из локального файла `.env` и дальше запускается
без повторного ввода ключа.

---

## Возможности

* чтение API key из `.env` (пакет `python-dotenv`), ключ **не хардкодится** в коде;
* `GET /api/agents/listings/live` — обнаружение заданий, включая скрытые
  `AGENT_ONLY` / `AGENT_ALLOWED` (Agent API **не** считается источником актуального статуса);
* `GET /api/agents/listings/details/{slug}` — детали конкретного задания;
* публичная лента сайта (страницы + публичный JSON-фид) — актуальные задания;
* объединение источников по `slug` с флагами `source_api` / `source_website`;
* проверка каждой карточки: `verify_listing_card(slug)` возвращает `VERIFIED_OPEN` /
  `EXPIRED` / `CLOSED` / `COMPLETED` / `WINNERS_ANNOUNCED` / `NOT_FOUND` / `UNKNOWN`;
* фильтр актуальности (только `VERIFIED_OPEN` с непрошедшим deadline) и
  анализ финансового риска (`financial_risk`, `requires_own_money`);
* детерминированный скоринг `score_listing()`: `score`, `score_breakdown`,
  `estimated_fit`, `skills`, `hours_until_deadline`, `submissions`,
  `eligibility_status` (без внешнего AI);
* разделы вывода `=== TOP OPPORTUNITIES ===`, `=== TOP AGENT-COMPATIBLE ===`,
  `=== TOP HUMAN-ONLY ===`;
* итоговый отчёт `superteam_results.json` (+ `verified_listings.json`);
* авторизация через заголовок `Authorization: Bearer <SUPERTEAM_API_KEY>`;
* понятная обработка HTTP-кодов 400 / 401 / 403 / 404 / 429 / 500+;
* timeout для всех HTTP-запросов (20 с на запрос, 10 с на подключение),
  до 2 повторов для временных ошибок;
* безопасный вывод: ключ, `claimCode` и заголовок `Authorization` не печатаются;
* режим `--raw` для просмотра фактической структуры JSON.

---

## Требования

* Windows 10/11, PowerShell
* Python 3.11+ (проверено на 3.14)
* VS Code (опционально)

---

## Установка (пошагово)

### 1. Создать виртуальное окружение

```powershell
cd D:\Projects\SuperteamAgent
python -m venv .venv
```

### 2. Активировать окружение

```powershell
.\.venv\Scripts\Activate.ps1
```

Если PowerShell блокирует активацию, разрешите локальные скрипты один раз:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Либо используйте `.\.venv\Scripts\activate.bat` из `cmd.exe`.

### 3. Установить зависимости

```powershell
python -m pip install -r requirements.txt
```

Устанавливаются только два пакета: `httpx` и `python-dotenv`.

Для запуска тестов дополнительно:

```powershell
python -m pip install -r requirements-dev.txt
```

> Если `pip` настроен на недоступный внутренний индекс (например, корпоративный
> `nexus`), установка может упасть с `NameResolutionError` / `No matching
> distribution found`. Тогда поставьте пакеты явно с официального индекса:
>
> ```powershell
> python -m pip install --index-url https://pypi.org/simple -r requirements.txt
> ```

### 4. Создать/заполнить `.env`

Файл `.env` уже создан в корне проекта и содержит заглушку:

```
SUPERTEAM_API_KEY=PASTE_API_KEY_HERE
```

Замените `PASTE_API_KEY_HERE` на свой реальный API key агента Superteam Earn и сохраните файл.

* Ключ хранится **только** в `.env`.
* `.env` уже добавлен в `.gitignore`, поэтому в Git он не попадёт.
* Никогда не вставляйте ключ в исходники пакета, README или скриншоты.

### 5. Запустить

```powershell
python -m superteam_agent
```

Ожидаемый вывод (фактический прогон):

```
=== SUPERTEAM HYBRID SEARCH ===

Agent API listings: 9
Website listings: 22
Unique listings: 31
agent_api only: 9 | website only: 22 | both: 0

=== WEBSITE SOURCE DIAGNOSTICS ===

https://superteam.fun/earn
    HTTP: 200 | content-type: text/html; charset=utf-8 | bytes: 52195 | reachable: True
    __NEXT_DATA__: yes | embedded listing objects: 0 | /earn/listing/ links: 0
https://superteam.fun/earn/all
    HTTP: 200 | content-type: text/html; charset=utf-8 | bytes: 42753 | reachable: True
    __NEXT_DATA__: yes | embedded listing objects: 0 | /earn/listing/ links: 0
... (bounties, projects — так же)
https://superteam.fun/api/listings/?status=open (public feed used by the site frontend)
    HTTP: 200 | reachable: True | listings from feed: 22

=== CARD VERIFICATION ===

[1] Develop a narrative detection and idea generation tool
    Sources: agent_api
    API: OPEN / 2026-02-15 | WEBSITE: -
    CARD: WINNERS_ANNOUNCED
    Card info: card deadline: 2026-02-15 18:29 UTC (passed: yes) | winners: isWinnersAnnounced=true; ...
    Result: EXCLUDE

[2] ... (аналогично для каждого уникального задания)

=== VERIFIED OPEN ===

20

[1] Steve Agent Arena: Launch Your Agent & Win 500 USDC
    Slug: steve-agent-arena-launch-your-agent-and-win-500-usdc
    Reward: 500 USDC
    Deadline: 2026-09-20 21:59 UTC
    Type: bounty
    Agent access: AGENT_ALLOWED
    Region: Global (ELIGIBLE)
    Source: website
    Financial risk: MEDIUM
    Own money required: no
    Difficulty: MEDIUM
    Priority: MEDIUM (score 47, fit GOOD)
    Reason: reward currency USDC (crypto) -> +35; agent access AGENT_ALLOWED -> +20; ...
    Card: https://superteam.fun/earn/listing/steve-agent-arena-launch-your-agent-and-win-500-usdc

...

=== TOP OPPORTUNITIES ===

1

[1] Steve Agent Arena: Launch Your Agent & Win 500 USDC

Reward: 500 USDC
Deadline: 2026-09-20 21:59 UTC
Agent access: AGENT_ALLOWED
Region: Global
Difficulty: MEDIUM
Financial risk: MEDIUM
Own money: no
Estimated fit: GOOD
Score: 47
Why:
- reward currency USDC (crypto) -> +35
- agent access AGENT_ALLOWED -> +20
- tech: automation -> +12
Card: https://superteam.fun/earn/listing/steve-agent-arena-launch-your-agent-and-win-500-usdc

=== TOP AGENT-COMPATIBLE ===

1

[1] Steve Agent Arena: Launch Your Agent & Win 500 USDC
    Slug: steve-agent-arena-launch-your-agent-and-win-500-usdc
    Score: 47 | Fit: GOOD | Priority: MEDIUM
    Reward: 500 USDC | Deadline: 2026-09-20 21:59 UTC (151.7h)
    Agent access: AGENT_ALLOWED | Region: Global (ELIGIBLE)
    Difficulty: MEDIUM | Financial risk: MEDIUM | Own money: no
    Card: https://superteam.fun/earn/listing/steve-agent-arena-launch-your-agent-and-win-500-usdc

=== TOP HUMAN-ONLY ===

5

[1] Create an App on Cookie Chain
    Slug: create-an-app-on-cookie-chain-app
    Score: -35 | Fit: WEAK | Priority: LOW
    Reward: 1 000 USDC | Deadline: 2026-09-22 21:59 UTC (199.7h)
    Agent access: HUMAN_ONLY | Region: Global (ELIGIBLE)
    Difficulty: EASY | Financial risk: LOW | Own money: no
    Card: https://superteam.fun/earn/listing/create-an-app-on-cookie-chain-app

...

=== TOP AGENT-COMPATIBLE ===

1

[1] Colosseum Crypto World's Fair Hackathon | Superteam Vietnam Track
    Slug: colosseum-crypto-worlds-fair-hackathon-superteam-vietnam-track
    Score: 55 | Fit: GOOD | Priority: MEDIUM
    Reward: 10 000 USDC | Deadline: 2026-10-13 06:59 UTC (688.4h)
    Agent access: AGENT_ALLOWED | Region: Vietnam (REGION_RESTRICTED)
    Difficulty: MEDIUM | Financial risk: LOW | Own money: no
    Decision: CANDIDATE
    Exclusion reason: -
    Card: https://superteam.fun/earn/listing/colosseum-crypto-worlds-fair-hackathon-superteam-vietnam-track

=== TOP HUMAN-ONLY ===

5

[1] Create an App on Cookie Chain
    Slug: create-an-app-on-cookie-chain-app
    Score: -35 | Fit: WEAK | Priority: LOW
    Reward: 1 000 USDC | Deadline: 2026-09-22 21:59 UTC (199.7h)
    Agent access: HUMAN_ONLY | Region: Global (ELIGIBLE)
    Difficulty: EASY | Financial risk: LOW | Own money: no
    Card: https://superteam.fun/earn/listing/create-an-app-on-cookie-chain-app

...

=== EXCLUDED FOR FINANCIAL RISK ===

6

[1] Steve Agent Arena: Launch Your Agent & Win 500 USDC
    Slug: steve-agent-arena-launch-your-agent-and-win-500-usdc
    Reward: 500 USDC | Agent access: AGENT_ALLOWED
    Debug risk flags:
        requires_real_mainnet_activity=True | requires_real_trade=True
        requires_deposit=False | requires_token_purchase=False | requires_user_gas=False | requires_own_money=False
        financial_risk=HIGH
    Decision: EXCLUDE
    Exclusion reason: REAL_FINANCIAL_ACTIVITY_REQUIRED
        - requires_real_trade: qualifying trades -> "Complete at Least 5 Trades Execute at least 5 qualifying trades through your Steve Agent on Solana Mainnet."
        - requires_real_mainnet_activity: trades on mainnet -> "Complete at Least 5 Trades Execute at least 5 qualifying trades through your Steve Agent on Solana Mainnet."
    Note (does NOT override exclusion): description: Get Started ... Sponsored Free Lane ...
    Card: https://superteam.fun/earn/listing/steve-agent-arena-launch-your-agent-and-win-500-usdc

...

Статусы карточек: VERIFIED_OPEN=22, ..., WINNERS_ANNOUNCED=9, ...
Итого: уникальных 31, подтверждено открытых 17 (agent-compatible: 1), исключено 14 (из них по деньгам исполнителя: 6)
Результаты: D:\Projects\SuperteamAgent\superteam_results.json
Отчёт проверки карточек: D:\Projects\SuperteamAgent\verified_listings.json
```

Ключевой смысл: Agent API отдаёт `OPEN`, карточка — `WINNERS_ANNOUNCED` → `EXCLUDE`.
Актуальные задания приходят с публичной ленты сайта, подтверждаются карточкой и
ранжируются по score; human-only задачи вынесены в отдельный список.

---

## Дополнительные режимы запуска

| Команда | Что делает |
| --- | --- |
| `python -m superteam_agent` | гибридный поиск: Agent API + сайт + проверка всех карточек + оценки |
| `python -m superteam_agent --verify-limit 10` | проверить карточки только для первых 10 уникальных заданий (0 = все) |
| `python -m superteam_agent --no-verify` | без проверки карточек (только данные источников) |
| `python -m superteam_agent --show 25` | сколько записей показать в режиме `--no-verify` |
| `python -m superteam_agent --details 5` | дополнительно запросить Agent API details для первых 5 кандидатов |
| `python -m superteam_agent --slug some-slug` | запросить Agent API details для конкретного slug |
| `python -m superteam_agent --raw` | напечатать JSON ответов API (секреты вырезаны) |
| `python -m superteam_agent --no-diagnostics` | не проверять диагностические страницы `/earn*` (только публичный JSON-фид) |

`--raw` полезен, если структура JSON на сервере отличается от ожидаемой:
вы видите фактический ответ (уже без секретов) и можете адаптировать поля.

---

## HYBRID SEARCH: два источника + карточка как истина

Итог этапа 2 подтвердился на живых данных: **Agent API отдаёт устаревшие задания**
(`status=OPEN` у карточек с объявленными winners). Поэтому роли распределены так:

| Источник | Роль | Что берём |
| --- | --- | --- |
| Agent API `/api/agents/listings/live` | **обнаружение**, в т.ч. скрытых `AGENT_ONLY` | `title`, `slug`, `type`, `reward`, `agentAccess`, API `deadline` |
| Публичный сайт | актуальная лента | `title`, `slug`, `reward`, `deadline`, `type`, `agentAccess`, `status`, `region` |
| Карточка `/earn/listing/{slug}` | **главный источник истины** | фактический статус, deadline, reward, winners, region, description, agent access |

Статус/дедлайн Agent API **не считаются достаточными** — они сохраняются только как
исторические значения (`api_status`, `api_deadline`), а решение принимается по карточке.

### Как получается лента с публичного сайта

Проверено фактически (`GET` через httpx, без авторизации и без Playwright):

| URL | HTTP | Что найдено |
| --- | --- | --- |
| `https://superteam.fun/earn` | 200 | `__NEXT_DATA__` есть, но в `pageProps` только `potentialSession/totalSponsors/totalUsers`; **0** ссылок `/earn/listing/`, **0** объектов заданий |
| `https://superteam.fun/earn/all` | 200 | то же (только `potentialSession`) |
| `https://superteam.fun/earn/bounties` | 200 | то же |
| `https://superteam.fun/earn/projects` | 200 | то же |
| `https://superteam.fun/earn/development` | **404** | такого маршрута нет (как и `/earn/dev`, `/earn/content`, `/earn/design`) |
| `https://superteam.fun/_next/data/{buildId}/earn.json` | 200 | те же пустые `pageProps` |
| `https://superteam.fun/api/listings/?status=open` | 200 | **22 актуальных задания** (`bounty`/`project`) с `slug`, `title`, `status`, `agentAccess`, `deadline`, `rewardAmount`, `token`, `isWinnersAnnounced`, `winnersAnnouncedAt` |

Вывод: HTML и Next.js payload карточек не содержат, поэтому источником №2 служит
публичный JSON-фид, который использует сам frontend сайта (тот же домен, без ключа).
Диагностика по каждому URL печатается в секции `=== WEBSITE SOURCE DIAGNOSTICS ===`.

### Объединение и фильтрация

* задания объединяются по `slug`;
* `source_api` / `source_website` показывают, где найдено задание (оба могут быть `true`);
* каждая уникальная карточка проверяется через `verify_listing_card(slug)`;
* в финал попадают только `VERIFIED_OPEN` **с подтверждённым deadline в будущем**;
* winners / completed / closed / expired / deadline passed → `EXCLUDE`, даже если API говорит `OPEN`;
* при недоступности сайта статус `UNKNOWN` — задание **не** считается закрытым.

### Финансовый риск

Правила вынесены в отдельный подраздел «Финансовый риск: реальная mainnet-активность»
ниже: `analyze_financial_risk(description, requirements, eligibility)`, флаги
`requires_real_mainnet_activity` / `requires_real_trade` / `requires_deposit` /
`requires_token_purchase` / `requires_user_gas` / `requires_own_money`,
`financial_risk`, `risk_reasons`, `decision`, `exclusion_reason`.

### Приоритеты и сложность

Балл складывается из: крипто-выплаты (`USDC`/`USDT` +30, `SOL` +25, другие стейблы +15…22,
неизвестный токен +10), agent-compatibility (`AGENT_ONLY` +20, `AGENT_ALLOWED` +12,
`HUMAN_ONLY` −25), стека (Python +12, Playwright +12, scraping +12, automation +10,
API +8, testing +8, JavaScript +8, HTML/CSS +6; суммарно не более +30),
beginner-friendly (+10) и штрафов (Rust/Solana protocol −15, узкая blockchain-специализация −15,
design −12, content −10, marketing −10, финансовый риск MEDIUM −10).

`priority`: `HIGH` при балле ≥ 60, `MEDIUM` ≥ 35, иначе `LOW`.
`difficulty`: `HARD` при Rust/on-chain/криптографии или требовании своих денег,
`EASY` при beginner-маркерах (или небольшом стековом задании), иначе `MEDIUM`.

### Файлы результата

`superteam_results.json` — основной результат:

```json
{
  "timestamp_utc": "2026-09-14T14:05:00Z",
  "agent_api_count": 9,
  "website_count": 22,
  "unique_count": 31,
  "verified_open_count": 20,
  "website_diagnostics": [ { "url": "...", "http_status": 200, "next_data_found": true, "embedded_listings_found": 0, "listing_links_found": 0 } ],
  "website_feed": { "url": "https://superteam.fun/api/listings/?status=open", "items": 22 },
  "top_agent_compatible": [ { "slug": "...", "title": "...", "score": 47, "estimated_fit": "GOOD", "agent_access": "AGENT_ALLOWED" } ],
  "top_human_only": [ { "slug": "...", "title": "...", "score": -35, "estimated_fit": "WEAK", "agent_access": "HUMAN_ONLY" } ],
  "listings": [
    {
      "slug": "steve-agent-arena-launch-your-agent-and-win-500-usdc",
      "title": "Steve Agent Arena: Launch Your Agent & Win 500 USDC",
      "source_api": false,
      "source_website": true,
      "status": "OPEN",
      "deadline": "2026-09-20T21:59:59.000Z",
      "deadline_utc": "2026-09-20 21:59 UTC",
      "reward_amount": 500.0,
      "reward_currency": "USDC",
      "reward_type": "crypto",
      "agent_access": "AGENT_ALLOWED",
      "region": "Global",
      "eligibility_status": "ELIGIBLE",
      "difficulty": "MEDIUM",
      "financial_risk": "MEDIUM",
      "requires_own_money": false,
      "requires_real_mainnet_activity": false,
      "requires_real_trade": false,
      "requires_deposit": false,
      "requires_token_purchase": false,
      "requires_user_gas": false,
      "risk_reasons": ["trading mentioned in text ('trading') - verify if own funds are needed"],
      "decision": "CANDIDATE",
      "exclusion_reason": "",
      "skills": ["automation"],
      "hours_until_deadline": 151.7,
      "submissions": 19,
      "score": 47,
      "score_breakdown": {
        "reward_score": 35, "agent_score": 20, "tech_score": 12, "difficulty_score": 5,
        "competition_score": 5, "time_score": -5, "risk_penalty": -25,
        "region_penalty": 0, "nontech_penalty": 0, "protocol_penalty": 0
      },
      "verification_status": "VERIFIED_OPEN",
      "card_url": "https://superteam.fun/earn/listing/steve-agent-arena-launch-your-agent-and-win-500-usdc",
      "final_decision": "CANDIDATE",
      "estimated_fit": "GOOD",
      "why": ["reward currency USDC (crypto) -> +35", "..."],
      "exclusion_reasons": []
    }
  ]
}
```

`verified_listings.json` — отчёт проверки карточек (совместимость с этапом 2).

Оба файла пересоздаются при каждом запуске и добавлены в `.gitignore`.
Секреты в них не попадают: JSON прогоняется через `redact()`.

---

## Проверка актуальности по публичной карточке (этап 2)

Agent API может возвращать **устаревшие** задания. Поэтому статус из API
(`status=OPEN` + `deadline`) не считается достаточным: для каждого задания
скачивается публичная карточка

```
https://superteam.fun/earn/listing/{slug}
```

обычным HTTP GET через `httpx` (без Playwright) и анализируется её реальное
содержимое.

### Откуда берутся данные карточки (проверено на живом сайте)

* `__NEXT_DATA__` → `props.pageProps.listing` — полный объект задания:
  `status`, `deadline`, `commitmentDate`, `isWinnersAnnounced`,
  `winnersAnnouncedAt`, `region`, `agentAccess`, `rewardAmount`, `token`,
  `rewards`, `description`, `skills`;
* JSON-LD (`schema.org/JobPosting`): `title`, `description`, `validThrough`,
  `baseSalary`, `jobLocation.address.addressCountry`;
* meta-теги (`og:title`, `og:description`);
* видимый текст страницы (после удаления `<script>`/`<style>`);
* `dehydratedState` (react-query): при объявленных winners появляется
  запрос `["winners", <listingId>]`.

Важные факты, влияющие на логику:

1. поле `status` у карточки остаётся `OPEN` **даже у завершённых заданий** —
   опираться только на него нельзя;
2. несуществующий slug отдаёт **HTTP 200 с `listing = null`** (не 404);
3. у winners-карточек заполнен `winnersAnnouncedAt` и есть query `winners`;
4. региональные ограничения видны в поле `region` и в тексте блока
   «REGIONAL LISTING … only open for people in …».

### Значения `verification_status`

| Статус | Значение |
| --- | --- |
| `VERIFIED_OPEN` | карточка существует, submissions открыты, deadline не прошёл |
| `EXPIRED` | deadline карточки уже прошёл (даже если API говорит OPEN) |
| `CLOSED` | статус/unpublished/текст говорят о закрытии или приёме заявок завершён |
| `COMPLETED` | карточка сообщает о завершении задания |
| `WINNERS_ANNOUNCED` | объявлены winners (`isWinnersAnnounced`, `winnersAnnouncedAt`, query `winners`, текст) |
| `NOT_FOUND` | HTTP 404 или `listing = null` (карточки нет) |
| `UNKNOWN` | сайт недоступен/данных недостаточно — задание **не** считается закрытым |

### Порядок принятия решения

Статус определяется **совокупностью** сигналов, а не одним ключевым словом:

1. winners (structured → query → текст) → `WINNERS_ANNOUNCED`;
2. deadline карточки < текущего времени UTC → `EXPIRED`;
3. закрытие (текст, `isPublished=false`, статус closed/cancelled) → `CLOSED`;
4. статус completed/finished → `COMPLETED`; статус review/judging → `CLOSED`;
5. статус open и deadline не прошёл (или deadline на карточке нет) → `VERIFIED_OPEN`;
6. иначе → `UNKNOWN`.

Метка результата в консоли: `VERIFIED_OPEN` → `CANDIDATE`,
`UNKNOWN` → `MANUAL_CHECK`, остальное → `EXCLUDE`.

### Файл `verified_listings.json`

Сохраняется в корне проекта при каждом запуске:

```json
{
  "timestamp_utc": "2026-09-14T13:34:59Z",
  "api_count": 9,
  "verified_count": 0,
  "verification_summary": { "VERIFIED_OPEN": 0, "EXPIRED": 0, "WINNERS_ANNOUNCED": 9, "...": 0 },
  "listings": [ { "slug": "...", "card_url": "...", "verification_status": "WINNERS_ANNOUNCED", "...": "..." } ]
}
```

Файл содержит те же поля, что возвращает `verify_listing_card(slug)`, плюс
`api_title`, `api_status`, `api_deadline`, `result`. Секретов в нём нет: перед
записью весь JSON прогоняется через redaction. Файл добавлен в `.gitignore`
(это результат запуска, а не исходник).

### Надёжность проверки

* timeout 20 секунд на карточку, 10 секунд на подключение;
* до 2 повторов при таймауте, сетевой ошибке, 429 и 5xx (с паузой 2 и 4 с);
* 404 и другие постоянные ошибки не повторяются;
* при недоступности сайта задание получает `UNKNOWN` и **не** исключается как закрытое.

---

## INTELLIGENT FILTERING + RANKING (этап 4)

Скоринг полностью детерминированный (правила + регулярные выражения), внешний AI
не используется. Источник истины — карточка: в финал попадают только
`VERIFIED_OPEN` с подтверждённым непрошедшим дедлайном.

### Жёсткие исключения (`HARD EXCLUDE`)

| Условие | Почему |
| --- | --- |
| `verification_status` ≠ `VERIFIED_OPEN` (`EXPIRED`/`CLOSED`/`COMPLETED`/`WINNERS_ANNOUNCED`/`NOT_FOUND`/`UNKNOWN`) | карточка — источник истины |
| дедлайн на карточке не найден или уже прошёл | актуальность |
| `winners already announced` | задание закрыто |
| `decision = EXCLUDE` с `exclusion_reason = REAL_FINANCIAL_ACTIVITY_REQUIRED` | для обязательной части нужна реальная mainnet-финансовая активность |
| региональное ограничение несовместимо с вашим регионом | задание недоступно |

`financial_risk=MEDIUM` **не исключается**, но получает `-25` к score и причину
в `risk_reasons` (например «trading mentioned in text — verify if own funds are
needed»).

### Финансовый риск: реальная mainnet-активность

Функция (детерминированная, без внешнего AI):

```python
analyze_financial_risk(description: str, requirements: str, eligibility: str) -> dict
```

Она анализирует полный текст описания карточки (не обрезанный), блок `requirements`
и текст eligibility-вопросов (последние считаются обязательными требованиями).
Результат содержит флаги:

| Поле | Значение |
| --- | --- |
| `requires_real_mainnet_activity` | требуется реальная активность в mainnet |
| `requires_real_trade` | реальные сделки/свапы/позиции/торговый конкурс |
| `requires_deposit` | депозит или пополнение баланса |
| `requires_token_purchase` | покупка/продажа токенов |
| `requires_user_gas` | исполнитель платит gas/transaction fees |
| `requires_own_money` | использование собственных USDC/USDT/SOL/ETH |
| `financial_risk` | `LOW` / `MEDIUM` / `HIGH` |
| `risk_reasons` | список причин с цитатами из карточки |
| `hard_exclusion`, `exclusion_reason` | `True` + `REAL_FINANCIAL_ACTIVITY_REQUIRED` |

**Правило decision:** если любой из флагов `true` → `decision = EXCLUDE` и
`exclusion_reason = REAL_FINANCIAL_ACTIVITY_REQUIRED`; `financial_risk = HIGH`
исключается; `MEDIUM` остаётся кандидатом, но с сильным понижением score.

**Sponsored Free Lane / Free Lane / sponsor pays gas / credits / free trial
НЕ отменяют исключение**, если обязательное требование — реальная торговля.
Такие пометки сохраняются в `risk_non_overriding_notes` и печатаются в отчёте.
`sponsor pays gas` / `gasless` снимают только флаг `requires_user_gas`.

Триггеры (смысловые варианты, а не только точные слова):

* **торговля:** real trade/real trading, mainnet trade/trading, trades on mainnet,
  on-chain trade, qualifying trades, complete/execute N trades, execute trades,
  place orders, open/close positions, swap tokens, Jupiter swap, perps/perpetual
  futures, trading competition/league, trading volume/activity, PnL, trade to earn/qualify;
* **деньги:** deposit, top-up/recharge/add funds/fund your wallet, use your funds,
  your own USDC/USDT/SOL/ETH, buy/purchase tokens, pay gas, gas/transaction fees,
  minimum balance, hold at least $N worth.

Что **не** считается триггером (важное отличие): упоминание «trade»/«trading» без
обязательной финансовой активности — «Build a trading simulator», «Read historical
trade data», «Review a trading interface without performing transactions»; описание
продукта спонсора («users can deposit…», «enabling users to buy…»); требование к
создаваемому продукту («your application must allow users to…») — это context/MEDIUM.

Разрешённые режимы (→ `LOW`, `requires_own_money = false`): testnet, devnet,
sandbox, mock, simulated/paper trading, faucet tokens, fake/dummy tokens,
local blockchain/net/local validator, free API sandbox.

### Разделы вывода

* `=== TOP OPPORTUNITIES ===` — до 3 заданий с **положительным** score (в формате
  Reward / Deadline / Agent access / Region / Difficulty / Financial risk /
  Own money / Estimated fit / Score / Why / Card);
* `=== TOP AGENT-COMPATIBLE ===` — только `AGENT_ONLY` / `AGENT_ALLOWED` (до 5);
  задания с `decision = EXCLUDE` сюда **не попадают никогда**, даже если
  `own money required = false`;
* `=== TOP HUMAN-ONLY ===` — только `HUMAN_ONLY` (до 5), чтобы такие задачи не
  смешивались с основной выдачей;
* `=== EXCLUDED FOR FINANCIAL RISK ===` — задания с
  `exclusion_reason = REAL_FINANCIAL_ACTIVITY_REQUIRED` (флаги + цитаты из карточки);
* `=== VERIFIED OPEN ===` — полный список всех прошедших фильтр.

В каждом элементе печатаются строки `Decision:` и `Exclusion reason:`.

### Веса скоринга

```
score = reward_score + agent_score + tech_score + difficulty_score
      + competition_score + time_score
      - risk_penalty - region_penalty - nontech_penalty - protocol_penalty
```

| Компонент | Правило |
| --- | --- |
| `reward_score` | USDC +35, USDT +35, SOL +30, jupUSD +25, USDG +20, прочие крипто/стейблы +15, фиат 0, неизвестно 0 |
| `agent_score` | AGENT_ONLY +30, AGENT_ALLOWED +20, UNKNOWN 0, HUMAN_ONLY −100 |
| `tech_score` | Python +15, Playwright +15, scraping +15, automation +12, JS +12, testing/QA +12, API +10, CSV/Excel +10, HTML/CSS +10, backend +8, frontend +6 (сумма, cap +45) |
| `difficulty_score` | EASY +20, MEDIUM +5, HARD −20, UNKNOWN 0 |
| `competition_score` | submissions 0–10 +10, 11–30 +5, 31–100 0, >100 −10, неизвестно 0 |
| `time_score` | >7 дней 0, 3–7 дней −5, 1–3 дня −10, <24 ч −20 (не фильтр!) |
| `risk_penalty` | MEDIUM −25 (HIGH уже исключён) |
| `region_penalty` | ограничение региона без данных о вашем регионе −15 |
| `nontech_penalty` | design −15, content −15, marketing −20 |
| `protocol_penalty` | Rust/Solana protocol −10 (не запрет, только для beginner-профиля) |

`estimated_fit`: ≥70 `EXCELLENT`, ≥45 `GOOD`, ≥20 `FAIR`, иначе `WEAK`.
`priority`: ≥60 `HIGH`, ≥35 `MEDIUM`, иначе `LOW` (это же значение лежит в `score`).

### Регион (`eligibility_status`)

* `region=Global`/пусто и нет явных ограничений → `ELIGIBLE`, без штрафа;
* карточка явно ограничивает регион («only open for people in Thailand»,
  «restricted to Canada», «Nigeria only») → `REGION_RESTRICTED`;
* если регион пользователя **не задан**, задание не исключается, а получает
  `REGION_RESTRICTED` и −15 (решение за вами);
* чтобы исключение работало автоматически, задайте регион:

  ```powershell
  $env:SUPERTEAM_USER_REGION="Ukraine"     # можно несколько: "Ukraine, Europe"
  python -m superteam_agent
  ```

  При несовпадении задание получает `HARD EXCLUDE`, при совпадении — `ELIGIBLE`.

---

## Обработка ошибок

| Код | Сообщение скрипта |
| --- | --- |
| 200 | успех, JSON возвращается вызывающему коду |
| 400 | `Bad request (400): <безопасное описание ответа>` |
| 401 | `Authentication failed: check SUPERTEAM_API_KEY` |
| 403 | `Access forbidden (403): the agent is not allowed to use this endpoint` |
| 404 | `Resource not found (404)` |
| 429 | `Rate limit exceeded` |
| 500+ | `Server error (5xx) - try again later` |

---

## Структура проекта

```
D:\Projects\SuperteamAgent\
    .env                    # локальные секреты (в Git не коммитится)
    .env.example            # шаблон .env (SUPERTEAM_API_KEY=PASTE_API_KEY_HERE)
    .gitignore              # правила исключения (.env, .venv, отчёты, кэш)
    pyproject.toml          # метаданные пакета + настройки pytest
    requirements.txt        # httpx, python-dotenv
    requirements-dev.txt    # pytest (только для разработки)
    conftest.py             # подставляет корень проекта в sys.path для pytest
    README.md               # эта инструкция
    superteam_agent/        # пакет (весь код)
        __init__.py         # версия пакета
        __main__.py         # `python -m superteam_agent` → cli.main()
        cli.py              # argparse (--show/--details/--slug/--raw/--no-verify/
                            #   --verify-limit/--no-diagnostics), точка входа
        config.py           # константы, пути, таймауты, DEFAULT_BASE_URL
        secrets.py          # get_api_key, redact/safe/to_safe_json (маскирование)
        errors.py           # SuperteamApiError
        httpx_layer.py      # build_client, RateLimiter, fetch_page (повторы/429/5xx)
        api.py              # get_live_listings, get_listing_details, get_headers
        parse.py            # разбор JSON/HTML: lookup, extract_listings, formatters
        card.py             # verify_listing_card, decide_verification_status
        website.py          # collect_website_source (фид + диагностика), merge_sources
        risk.py             # analyze_financial_risk (mainnet-активность, флаги)
        scoring.py          # score_listing, reward/tech/difficulty/region/time info
        output.py           # печать секций и запись JSON-отчётов
        runner.py           # build_final_entry, async run_hybrid_search
    tests/                  # pytest: 6 тестовых модулей, 63 теста
        test_secrets.py     # маскирование ключей, to_safe_json
        test_card.py        # e2e на httpx.MockTransport (фикстуры HTML-карточек)
        test_risk.py        # правила финансового риска (trades/testnet/deposit)
        test_scoring.py     # breakdown score, hard exclusions, region, fit
        test_merge.py       # объединение источников по slug
        test_utils.py       # парсеры/форматтеры (JSON-LD, meta, next_data и др.)
    superteam_results.json  # результат гибридного поиска (создаётся автоматически)
    verified_listings.json  # отчёт проверки карточек (создаётся автоматически)
```

Код модульный: каждый модуль отвечает за один слой (конфигурация, секреты,
HTTP, Agent API, парсинг, карточка, сайт, риск, скоринг, вывод, прогон, CLI).
Запросы к Agent API идут на `https://superteam.fun` (можно переопределить через
`SUPERTEAM_API_BASE_URL`), карточки и публичная лента — с того же домена
(`/earn/listing/{slug}`, `/api/listings/?status=open`). Весь сетевой код
асинхронный (`httpx.AsyncClient`, один клиент на прогон), точка входа —
`asyncio.run(run_hybrid_search(args))`.

---

## Тесты

* 63 теста, `pytest`; синхронные тесты + асинхронный e2e через `asyncio.run`
  (плагин `pytest-asyncio` не нужен);
* реальные запросы не отправляются: Agent API и карточки — на фикстурах HTML и
  `httpx.MockTransport`, секреты — на заведомо подставленных значениях;
* покрываются: маскирование секретов, e2e проверки карточки (открытая/ winners/
  expired/ closed/ null/404/403/submissionCount), правила финансового риска,
  breakdown score и hard exclusions, объединение источников, парсеры.

```powershell
python -m pytest -q
```

Ожидаемый результат: `63 passed`.

---

## Безопасность

1. API key хранится только в `.env` и никогда не попадает в `.py`-файлы.
2. `.env` добавлен в `.gitignore` — секрет не уйдёт в Git.
3. Вывод прогоняется через `redact()`: ключ и заголовок `Authorization` в консоль
   не попадают даже при ошибке сервера.
4. Тело ответа обрезается (`MAX_RESPONSE_SNIPPET = 300`) и не печатается целиком
   в сообщениях об ошибках.
5. Перед первым коммитом проверьте статус:

   ```powershell
   git status
   git check-ignore -v .env
   ```

   Вторая команда должна показать, что `.env` игнорируется.

---

## Диагностика проблем

| Проблема | Решение |
| --- | --- |
| `SUPERTEAM_API_KEY is not set` | заполните `.env` и сохраните файл (без кавычек и пробелов) |
| `Authentication failed: check SUPERTEAM_API_KEY` | ключ неверный/просрочен/отозван — проверьте значение в `.env` |
| `Access forbidden (403)` | ключ есть, но у агента нет доступа к эндпоинту/заданию |
| `Rate limit exceeded` | подождите и запустите снова, не делайте частых запросов |
| `Request timed out after 20s` | проверьте интернет/прокси, запустите повторно |
| `Response is not valid JSON` | запустите с `--raw`, чтобы увидеть фактический ответ |
| Пустой список заданий | на момент запуска живых заданий нет или изменилась схема — смотрите `--raw` |
| `agent_api only: 9 | website only: 22 | both: 0` | Agent API отдаёт отдельный (устаревший) набор; актуальные задания приходят из публичной ленты сайта |
| Все задания `WINNERS_ANNOUNCED` | это верное поведение: Agent API устарел, карточка — источник истины |
| `REGION_RESTRICTED` в результатах | регион пользователя не задан: укажите `$env:SUPERTEAM_USER_REGION="Ukraine"` (или другую страну), чтобы совпадение/несовпадение считалось автоматически |
| Все задачи дополнительно помечены `HUMAN_ONLY` | в текущей ленте сайта нет агентских заданий: они появятся в `TOP AGENT-COMPATIBLE` (и `AGENT_ONLY` видны только через Agent API) |
| Кириллица «кракозябрами» | в интерактивном терминале Unicode выводится корректно; при перенаправлении вывода в файл запускайте `chcp 65001` и смотрите файл в VS Code |

---

## Дальнейшие этапы (roadmap)

Этап 1 (реализован) — надёжное authenticated подключение и получение заданий
через Agent API (`get_live_listings`, `get_listing_details`).

Этап 2 (реализован) — проверка актуальности каждого задания по публичной карточке
`https://superteam.fun/earn/listing/{slug}`: `verify_listing_card()`,
`verification_status`, отчёт `verified_listings.json`.

Этап 3 (реализован) — HYBRID SEARCH:

* Agent API как источник обнаружения (`AGENT_ONLY` / `AGENT_ALLOWED`) — статус API не считается истиной;
* публичная лента сайта как источник актуальных заданий;
* объединение по `slug` (`source_api` / `source_website`);
* проверка каждой карточки, фильтр `VERIFIED_OPEN` + непрошедший deadline;
* финансовый риск (`financial_risk`, `requires_own_money`) с исключением
  deposit/top-up/своих средств/реальных trades/gas/покупки токенов и разрешением
  testnet/sandbox/mock/faucet/test tokens;
* приоритеты (crypto reward, agent-compatible, стек, beginner-friendly) и сложность;
* итоговый отчёт `superteam_results.json`.

Этап 4 (реализован) — intelligent filtering + ranking:

* жёсткие исключения: не `VERIFIED_OPEN`, нет дедлайна/дедлайн прошёл, winners,
  `requires_own_money`, `financial_risk=HIGH`, несовместимый регион;
* отдельное жёсткое правило: любая обязательная реальная mainnet-финансовая
  активность (реальная торговля, свапы/perps/позиции, депозит, покупка токенов,
  свои средства, свой gas) → `decision = EXCLUDE`,
  `exclusion_reason = REAL_FINANCIAL_ACTIVITY_REQUIRED`; sponsored free lane /
  credits / free trial это не отменяют;
* deterministic rule-based `score_listing()` (reward / agent / tech / difficulty /
  competition / time / risk / region / nontech / protocol) + `score_breakdown` и `why`;
* `estimated_fit`, `skills`, `hours_until_deadline`, `submissions`, `eligibility_status`;
* разделы `=== TOP OPPORTUNITIES ===` (до 3), `=== TOP AGENT-COMPATIBLE ===`,
  `=== TOP HUMAN-ONLY ===` и полный `=== VERIFIED OPEN ===`;
* в `superteam_results.json` добавлены `top_agent_compatible` и `top_human_only`.

Этап 5 (план, по желанию) — не реализовано:

* подготовка черновика submission (по-прежнему **запрещено**);
* история прогонов и сравнение изменений между запусками;
* уведомления о новых подходящих заданиях.

Важно: скрипт ничего не изменяет на Superteam — только читает данные (Agent API),
публичную ленту и страницы карточек. Submission и авто-подача заявок не реализованы.

