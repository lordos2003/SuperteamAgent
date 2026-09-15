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
* Этап 5 — multi-source поиск оплачиваемых задач за пределами Superteam:
  GitHub Issues, Bounty Bureau, Opire, warpSpeed, OpenBounty (`--all-sources`)
  с обязательной проверкой первоисточника и жёстким финансовым/региональным фильтром.

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
  `VERIFIED_EXPIRED` / `VERIFIED_CLOSED` / `VERIFIED_WINNER_ANNOUNCED` /
  `VERIFIED_HUMAN_ONLY` / `UNKNOWN`;
* фильтр актуальности (только `VERIFIED_OPEN` с непрошедшим deadline) и
  анализ финансового риска (`financial_risk`, `requires_own_money`);
* детерминированный скоринг `score_listing()`: `score`, `score_breakdown`,
  `estimated_fit`, `skills`, `hours_until_deadline`, `submissions`,
  `eligibility_status` (без внешнего AI);
* финальная eligibility-фильтрация TOP — `is_agent_compatible(entry)`:
  одновременно `verification_status=VERIFIED_OPEN`, `final_decision=CANDIDATE`,
  `eligibility_status=ELIGIBLE`, `agent_access` ∈ {`AGENT_ONLY`, `AGENT_ALLOWED`},
  все флаги `requires_* = false` и `financial_risk != HIGH`;
* разделы вывода `=== TOP OPPORTUNITIES ===`, `=== TOP AGENT-COMPATIBLE ===`,
  `=== TOP HUMAN-ONLY ===`, `=== EXCLUDED: REGION ===`,
  `=== EXCLUDED: FINANCIAL RISK ===`, `=== EXCLUDED: HUMAN ONLY ===`,
  `=== MANUAL ELIGIBILITY CHECK ===`;
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

Устанавливаются `httpx`, `python-dotenv` и `openpyxl` (последний — только для
Excel-отчёта `superteam_report.xlsx`).

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
python superteam_agent.py        # или: python -m superteam_agent
```

Вывод — человекочитаемый отчёт (`AVAILABLE BOUNTIES` / `EXCLUDED` /
`UNKNOWN` / `SUMMARY`) со ссылкой на карточку каждого задания; он же
сохраняется в `superteam_report.md`. Технические детали — с флагом `--debug`,
технический JSON — с `--json`, повторный отчёт без обращений к сайту — `--report`.

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

=== EXCLUDED: REGION ===

1

[1] Colosseum Crypto World's Fair Hackathon | Superteam Vietnam Track
    Slug: colosseum-crypto-worlds-fair-hackathon-superteam-vietnam-track
    Score: 55 | Fit: GOOD | Priority: MEDIUM
    Reward: 10 000 USDC | Deadline: 2026-10-13 06:59 UTC (688.4h)
    Agent access: AGENT_ALLOWED | Region: Vietnam (REGION_RESTRICTED)
    Difficulty: MEDIUM | Financial risk: LOW | Own money: no
    Decision: EXCLUDE
    Exclusion reason: REGION_INELIGIBLE
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

=== EXCLUDED: FINANCIAL RISK ===

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
| `python superteam_agent.py` / `python -m superteam_agent` | гибридный поиск + короткая сводка в консоли + **Excel-отчёт** `superteam_report.xlsx` (листы `SUMMARY`/`AVAILABLE`/`EXCLUDED`/`UNKNOWN`) |
| `python superteam_agent.py --report` | только отчёт (Excel + консоль) по последнему прогону из `superteam_results.json` — без обращения к сайту |
| `python superteam_agent.py --json` | технический JSON (тот же документ, что сохраняется в `superteam_results.json`) |
| `python superteam_agent.py --debug` | подробный технический вывод: evidence карточек, диагностика источников, статусы, кэш |
| `python superteam_agent.py --verify-limit 10` | проверить карточки только для первых 10 уникальных заданий (0 = все) |
| `python superteam_agent.py --no-verify` | **только для отладки**: карточки не проверяются, поэтому все задания получают `UNKNOWN` и `EXCLUDE` (обычный режим всегда выполняет verification) |
| `python superteam_agent.py --show 25` | сколько записей показать в режиме `--no-verify` |
| `python superteam_agent.py --details 5` | (с `--debug`) дополнительно запросить Agent API details для первых 5 кандидатов |
| `python superteam_agent.py --slug some-slug` | (с `--debug`) запросить Agent API details для конкретного slug |
| `python superteam_agent.py --raw` | (с `--debug`) напечатать JSON ответов API (секреты вырезаны) |
| `python superteam_agent.py --no-diagnostics` | не проверять диагностические страницы `/earn*` (только публичный JSON-фид) |
| `python superteam_agent.py --all-sources` | multi-source поиск: Superteam + GitHub + Bounty Bureau + Opire + warpSpeed + OpenBounty |
| `python superteam_agent.py --all-sources --sources github,opire` | только выбранные источники (доступные имена см. ниже) |
| `python superteam_agent.py --all-sources --per-source-limit 10` | сколько записей брать из каждого источника (по умолчанию 25) |


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

Итоговый балл считается детерминированно по формуле из раздела «Веса скоринга»
ниже (`score_listing()`); здесь только пороги меток.

`priority`: `HIGH` при балле ≥ 60, `MEDIUM` ≥ 35, иначе `LOW` (значение совпадает со `score`).
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
| `VERIFIED_OPEN` | карточка открылась, подтверждает открытый bounty и deadline в будущем |
| `VERIFIED_EXPIRED` | deadline **карточки** уже прошёл (даже если API говорит OPEN) |
| `VERIFIED_CLOSED` | статус/unpublished/текст говорят о закрытии, completed или judging |
| `VERIFIED_WINNER_ANNOUNCED` | объявлены winners (`isWinnersAnnounced`, `winnersAnnouncedAt`, query `winners`, текст) |
| `VERIFIED_HUMAN_ONLY` | карточка явно помечает bounty как human-only (`agentAccess=HUMAN_ONLY`) |
| `UNKNOWN` | сайт недоступен / 404 / `listing = null` / нет deadline — статус определить нельзя |

`UNKNOWN` **никогда** не превращается в `VERIFIED_OPEN`: API-статус `OPEN` не
является доказательством, доказательство даёт только карточка.

Старые имена сохранены как алиасы (`CLOSED`/`COMPLETED` → `VERIFIED_CLOSED`,
`EXPIRED` → `VERIFIED_EXPIRED`, `WINNERS_ANNOUNCED` → `VERIFIED_WINNER_ANNOUNCED`,
`NOT_FOUND` → `UNKNOWN`), поэтому прежний код и отчёты продолжают читаться.

### Порядок принятия решения

Статус определяется **совокупностью** сигналов, а не одним ключевым словом:

1. winners (structured → query → текст) → `VERIFIED_WINNER_ANNOUNCED`;
2. deadline **карточки** < текущего времени UTC → `VERIFIED_EXPIRED`;
3. закрытие (текст, `isPublished=false`, статус closed/cancelled) → `VERIFIED_CLOSED`;
4. статус completed/finished → `VERIFIED_CLOSED`; статус review/judging → `VERIFIED_CLOSED`;
5. статус open и deadline с карточки в будущем → `VERIFIED_OPEN`;
5a. статус open, но deadline на карточке **не найден** → `UNKNOWN`
   (`deadline_confirmed=false` — подтвердить актуальность нельзя);
6. `agentAccess=HUMAN_ONLY` при открытой карточке → `VERIFIED_HUMAN_ONLY`;
7. иначе → `UNKNOWN`.

Метка результата в консоли: `VERIFIED_OPEN` → `CANDIDATE`,
`VERIFIED_HUMAN_ONLY` → `HUMAN_ONLY` (отдельный список, никогда не в агентские),
`UNKNOWN` → `MANUAL_CHECK`, остальное → `EXCLUDE`.

### API = discovery, card = verification

API и публичный фид используются только для **обнаружения** заданий. Итоговый
статус определяет карточка, и приоритет источников такой:

1. **verified card** — источник истины (статус, deadline, reward, token, agent access, winners, submissions);
2. **website data** — уточняет то, чего нет в карточке;
3. **API data** — только для обнаружения.

Расхождения не скрываются, а пишутся в отчёт: `api_status` / `api_deadline` /
`api_agent_access`, `website_status` / `website_deadline` / `website_reward`,
`verified_deadline` / `verified_reward` / `verified_currency` /
`verified_agent_access` / `verified_region` / `verified_winners` /
`verified_submissions` + `verification_url` / `verification_timestamp` и `evidence`.

Классический случай (проверено вживую): API отдаёт `OPEN` и deadline
`2026-03-16`, а карточка подтверждает `isWinnersAnnounced=true` → итог
`VERIFIED_WINNER_ANNOUNCED`, `final_decision = EXCLUDE`, приоритет `EXCLUDED`.

### Почему verification могла «пропускаться»

Обычный запуск (`python -m superteam_agent`) **всегда** проверяет карточки:
`--no-verify` — opt-in флаг для отладки, а не режим по умолчанию. Если он включён
(или задан слишком маленький `--verify-limit N`, из-за которого часть кандидатов
остаётся без проверки), то `_verify_cards()` возвращает `build_unverified_card()`,
и дальше всё идёт по цепочке:

```
verification_status = UNKNOWN  →  deadline_confirmed = false
   →  hard exclusion "card verification: UNKNOWN" + "deadline not confirmed on card"
   →  final_decision = EXCLUDE
```

Именно поэтому такие прогоны выглядят как «все задания исключены». Теперь:

* в начале секции `=== CARD VERIFICATION ===` печатается явное предупреждение,
  если `--no-verify` включён;
* `UNKNOWN` никогда не становится `VERIFIED_OPEN`, а попадает в
  `=== UNKNOWN / VERIFICATION FAILED ===` с причиной;
* в статистике видны `Verified` и `Unknown`, поэтому пропуск проверки заметен сразу.

### `verified_open_listings` (самый строгий список)

В `superteam_results.json` есть отдельный список `verified_open_listings` —
только листинги, которые **одновременно**:

* карточка реально открылась и подтверждает открытый bounty (`VERIFIED_OPEN`);
* deadline подтверждён карточкой (`deadline_confirmed = true`) и не прошёл;
* winners не объявлены;
* agent access определён явно и это не `HUMAN_ONLY` (`agent_access_unknown = false`);
* финансовый риск допустим (`LOW`, без флагов `requires_*`);
* проходят существующую финальную фильтрацию (`is_agent_compatible`: eligibility `ELIGIBLE`, `final_decision = CANDIDATE`).

Любой `UNKNOWN` в этот список попасть не может. Пустой список — нормальный
результат, если таких заданий сейчас нет.

### Кэш проверки карточек (TTL)

Чтобы не скачивать одну и ту же карточку в каждом прогоне, используется кэш
`verification_cache.json` с TTL (по умолчанию 900 секунд, настраивается
переменной окружения):

```powershell
$env:SUPERTEAM_VERIFICATION_CACHE_TTL = "3600"   # час
$env:SUPERTEAM_VERIFICATION_CACHE_TTL = "0"      # полностью отключить кэш
```

Устаревший статус не может «залипнуть»: по истечении TTL карточка скачивается
заново, а в `evidence` попадает строка вида
`verification reused from cache (age=42s, ttl=900s)`.

### Про Playwright

Playwright не нужен и не используется: карточка Superteam — серверный рендеринг,
и фактические данные лежат в HTML (`__NEXT_DATA__ → props.pageProps.listing`,
JSON-LD `JobPosting`, meta-теги). Проверено вживую (HTTP 200, полный объект
listing). Если сайт когда-нибудь перейдёт на клиентский рендеринг, карточка
станет `UNKNOWN` — это будет видно в `=== UNKNOWN / VERIFICATION FAILED ===`.

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
| `verification_status` ≠ `VERIFIED_OPEN` (`VERIFIED_EXPIRED`/`VERIFIED_CLOSED`/`VERIFIED_WINNER_ANNOUNCED`/`UNKNOWN`); `VERIFIED_HUMAN_ONLY` не исключается, но идёт только в human-only | карточка — источник истины |
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

### Excel-отчёт `superteam_report.xlsx` (основной результат)

Обычный запуск печатает **короткую** сводку в консоль и создаёт Excel-файл
`superteam_report.xlsx` с четырьмя листами: `SUMMARY`, `AVAILABLE`, `EXCLUDED`,
`UNKNOWN`. Главное правило: лист `AVAILABLE` заполняется ТОЛЬКО из результата
финальной фильтрации (`is_verified_open_listing()`), поэтому ссылка на
исключённое задание физически не может туда попасть.

Лист `AVAILABLE` (колонки `#`, `Priority`, `Score`, `Task`, `Reward Amount`,
`Currency`, `Deadline (UTC)`, `Days Left`, `Agent Access`, `Difficulty`, `Risk`,
`Eligibility`, `Region`, `Submissions`, `Type`, `What to build`, `Open Card`):
награда — отдельными числовыми колонками, дедлайн — настоящая дата Excel,
`Days Left` подсвечивается (≤3 дней — красным, ≤7 — жёлтым), `Priority`
закрашивается (HIGH/MEDIUM/LOW), а в колонке `Open Card` лежит **настоящая
гиперссылка** на `card_url` с коротким текстом (длинный URL в ячейке не выводится).

Лист `EXCLUDED` — для ручного анализа: `Why excluded` содержит короткую
человеческую причину (`Winners already announced`, `Human-only bounty`,
`Requires own funds`, `Region restriction`, `Deadline has passed`), сортировка —
сначала потенциально интересные (AGENT_ONLY/AGENT_ALLOWED → HUMAN_ONLY →
остальные), внутри группы по score. Технические формулировки остаются в JSON.

Консоль (обычный режим, без URL и без списка исключённых):

```text
============================================================
SUPERTEAM AGENT
============================================================

  Discovery:        33
  Unique:           32
  Verified:         32

  AVAILABLE:        0
  EXCLUDED:         32
  UNKNOWN:          0

No bounty passed all filters.

Excel report:
  D:\Projects\SuperteamAgent\superteam_report.xlsx

============================================================
```

Если подходящие задания есть, вместо строки `No bounty passed all filters.`
печатается короткий список (без URL):

```text
AVAILABLE FOR AGENT:

  1. Steve Agent Arena — 500 USDC — HIGH
  2. Build and Demo a Mermail Skill — 500 USDC — MEDIUM
```

Состав листов:

| Лист | Содержимое |
| --- | --- |
| `SUMMARY` | dashboard: Generated, Available / Excluded / Unknown, Verified / Discovered, разбивка (Agent Allowed, Human Only, Winner Announced, Risk Excluded, Expired) |
| `AVAILABLE` | только задания, прошедшие ВСЕ фильтры; ссылка `Open card` → `card_url` |
| `EXCLUDED` | исключённые задания с короткой причиной (для ручного анализа) |
| `UNKNOWN` | задания, у которых карточку проверить не удалось (НИКОГДА не в AVAILABLE) |

Особенности:

* на `AVAILABLE` ссылка оформлена как настоящая Excel-гиперссылка (`cell.hyperlink`),
  текст ячейки — короткий (`Open card`), длинный URL в ячейке не выводится;
* награда разделена на числовые колонки `Reward Amount` и `Currency`;
* дедлайн хранится как дата Excel (UTC) с форматом `dd mmm yyyy hh:mm` и колонкой
  `Days Left` (условное выделение: ≤3 дней — красным, ≤7 — жёлтым);
* таблицы с `freeze panes`, `autofilter`, автошириной колонок, границами и
  переносом текста; описания обрезаны (~320 символов);
* `superteam_report.md` остаётся как компактный Markdown-summary со ссылками,
  а `superteam_results.json` — как machine-readable источник (технические причины,
  evidence, `hard_exclusion_reasons`);

* `AVAILABLE FOR AGENT` — только задания, прошедшие `is_verified_open_listing()`
  (карточка подтвердила открытость, deadline подтверждён и в будущем, winners нет,
  agent access определён и это не `HUMAN_ONLY`, финансовый риск `LOW`,
  eligibility `ELIGIBLE`). Сортировка: priority → score ↓ → ближайший deadline;
* `EXCLUDED` — всё остальное, с короткой человеческой причиной
  («Winners have already been announced.», «Deadline has passed.»,
  «Requires own funds / financial risk.», «AI agents are not eligible (human-only bounty).»);
* `UNKNOWN / VERIFICATION FAILED` — карточку проверить не удалось; такие задания
  **никогда** не попадают в Available;
* `SUMMARY` — счётчики, посчитанные из фактических данных прогона.

Особенности:

* `Card:` — реальный `card_url` из проверки; в Windows Terminal это кликабельная
  ссылка (ANSI OSC 8), причём видимый текст — сам URL, поэтому fallback работает
  всегда. Отключить: `$env:SUPERTEAM_NO_HYPERLINKS="1"`;
* даты — `20 Sep 2026, 21:59 UTC` (внутри — timezone-aware datetime, снаружи —
  человеческий формат);
* `superteam_report.md` — тот же отчёт в Markdown со ссылками
  `[Open card](url)`, открывается в VS Code/GitHub;
* технические детали (`__NEXT_DATA__ present`, `pageProps.listing`, json-ld,
  UUID-запросы, `verification_skipped`, ключи кэша) в обычном режиме **не
  печатаются** — они доступны через `--debug`.

### Технические разделы (только `--debug`)

* `=== VERIFIED OPEN ===` — список `verified_open_listings`: только подтверждённые
  карточкой открытые задачи, подходящие агенту (reward / deadline / agent access /
  risk / score / URL);
* `=== TOP OPPORTUNITIES ===` — до 3 заданий с **положительным** score (в формате
  Reward / Deadline / Agent access / Region / Difficulty / Financial risk /
  Own money / Estimated fit / Score / Why / Card);
* `=== TOP AGENT-COMPATIBLE ===` — только записи, проходящие финальную проверку
  `is_agent_compatible(entry)` (до 5): `verification_status = VERIFIED_OPEN`,
  `final_decision = CANDIDATE`, `eligibility_status = ELIGIBLE`,
  `agent_access` ∈ {`AGENT_ONLY`, `AGENT_ALLOWED`}, все флаги `requires_*` равны
  `false` и `financial_risk != HIGH`; задания с `decision = EXCLUDE` сюда
  **не попадают никогда**, даже если `own money required = false`;
* `=== TOP HUMAN-ONLY ===` — только `HUMAN_ONLY` (до 5), чтобы такие задачи не
  смешивались с основной выдачей;
* `=== EXCLUDED: REGION ===` — кандидаты с `eligibility_status = REGION_RESTRICTED`
  (им проставляются `decision = EXCLUDE`, `exclusion_reason = REGION_INELIGIBLE`);
* `=== EXCLUDED: FINANCIAL RISK ===` — задания с
  `exclusion_reason = REAL_FINANCIAL_ACTIVITY_REQUIRED` (флаги + цитаты из карточки);
* `=== EXCLUDED: HUMAN ONLY ===` — тот же список `HUMAN_ONLY`, что и в
  `=== TOP HUMAN-ONLY ===` (печатается отдельно, как исключённый из агентской выдачи);
* `=== MANUAL ELIGIBILITY CHECK ===` — кандидаты с `eligibility_status = UNKNOWN`
  (печатается только если такие есть);
* `=== EXCLUDED ===` — все исключённые задачи: Title / Status / Reason / URL;
* `=== UNKNOWN / VERIFICATION FAILED ===` — задачи, по которым статус определить
  не удалось, с причиной и evidence (сайт/парсер/404/нет deadline);
* `=== STATISTICS ===` — итоговые счётчики: Discovered, Unique, Pre-filtered,
  Verified, Verified Open, Expired, Closed, Human Only, Winner Announced,
  Unknown, Risk Excluded;
* `=== VERIFIED OPEN ===` — полный список всех прошедших фильтр (см. выше).

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

* в TOP-разделах записи с `REGION_RESTRICTED` попадают в `=== EXCLUDED: REGION ===`
  (`decision = EXCLUDE`, `exclusion_reason = REGION_INELIGIBLE`), а кандидаты с
  неопределённым регионом (`UNKNOWN`) — в `=== MANUAL ELIGIBILITY CHECK ===`.

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
        output.py           # печать технических секций и запись JSON-отчётов
        report.py           # разделы отчёта, причины, компактный консольный вывод, Markdown
        excel_report.py     # Excel-отчёт (openpyxl): SUMMARY / AVAILABLE / EXCLUDED / UNKNOWN
        runner.py           # build_final_entry, async run_hybrid_search, --report
        cache.py            # TTL-кэш проверки карточек (verification_cache.json)
        multi_source.py     # --all-sources: дедупликация, классификация, bounty_results.json
        core/               # ядро multi-source (не зависит от конкретных источников)
            models.py       # единая модель задачи, разбор награды/валюты, ключи дедупликации
            verification.py # проверка первоисточника: GitHub issue, страница bounty
            filters.py      # политика: финансы, регион, human-only, награда, aggregator-посты
            ranking.py      # ранжирование: crypto → no-risk → open → beginner → reward → region
        sources/            # адаптеры источников (независимые модули)
            base.py         # SourceResult, fetch_json, probe_hosts, finalize_candidate
            superteam.py    # существующая гибридная логика Superteam
            github.py       # GitHub Search API + проверка issue
            bountybureau.py # /api/bounties (certified) + проверка issue
            opire.py        # api.opire.dev/rewards + проверка issue
            warpspeed.py    # честная проверка хостов (сейчас NOT_FOUND)
            openbounty.py   # честная проверка хостов (сейчас NOT_FOUND)
    tests/                  # pytest: 13 тестовых модулей, 145 тестов
        test_secrets.py     # маскирование ключей, to_safe_json
        test_card.py        # e2e на httpx.MockTransport (фикстуры HTML-карточек)
        test_risk.py        # правила финансового риска (trades/testnet/deposit)
        test_scoring.py     # breakdown score, hard exclusions, region, fit
        test_merge.py       # объединение источников по slug
        test_utils.py       # парсеры/форматтеры (JSON-LD, meta, next_data и др.)
        test_models.py      # разбор награды/валюты, ключи дедупликации
        test_verification.py# closed/assigned/merged PR/claimed/rate limit (MockTransport)
        test_filters.py     # финансовый фильтр, регион, human-only, «нет суммы»
        test_multi_source.py# дедупликация, классификация, ранжирование, отчёт
        test_verification_flow.py # 9 сценариев card verification + TTL-кэш
        test_report.py      # человекочитаемый отчёт: 14 сценариев
        test_excel_report.py# Excel: листы, гиперссылки, сортировка, summary
    superteam_results.json  # результат гибридного поиска (создаётся автоматически)
    verified_listings.json  # отчёт проверки карточек (создаётся автоматически)
    bounty_results.json     # сводный отчёт multi-source поиска (создаётся автоматически)
    superteam_report.xlsx   # Excel-отчёт (создаётся автоматически)
    superteam_report.md     # компактный Markdown summary (создаётся автоматически)
    verification_cache.json # TTL-кэш проверки карточек (создаётся автоматически)
    superteam_agent.py      # лончер: python superteam_agent.py == python -m superteam_agent
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

* 145 тестов, `pytest`; синхронные тесты + асинхронный e2e через `asyncio.run`
  (плагин `pytest-asyncio` не нужен);
* реальные запросы не отправляются: Agent API и карточки — на фикстурах HTML и
  `httpx.MockTransport`, секреты — на заведомо подставленных значениях;
* покрываются: маскирование секретов, e2e проверки карточки (открытая/ winners/
  expired/ closed/ null/404/403/submissionCount), правила финансового риска,
  breakdown score и hard exclusions, объединение источников, парсеры;
* multi-source: `tests/test_models.py` (разбор награды/валюты),
  `tests/test_verification.py` (closed/assigned/merged PR/claimed/rate limit),
  `tests/test_filters.py` (финансы, регион, human-only, награда),
  `tests/test_multi_source.py` (дедупликация, классификация, ранжирование);
* пайплайн карточек: `tests/test_verification_flow.py` — девять обязательных
  сценариев (expired/closed/winners/human-only/unknown, приоритет карточки над API,
  `agent_access_unknown`, eligible-кандидат) + поведение TTL-кэша;
* отчёт: `tests/test_report.py` — 14 сценариев (Available/Excluded/Unknown,
  ссылка на карточку, Markdown-ссылка, сортировка, summary, приоритет карточки);
* Excel: `tests/test_excel_report.py` — 16 сценариев (листы SUMMARY/AVAILABLE/
  EXCLUDED/UNKNOWN, гиперссылки ведут на `card_url`, исключённые задачи не попадают
  на `AVAILABLE`, сортировка `EXCLUDED`, разделение reward/currency, подсветка срочности).

```powershell
python -m pytest -q
```

Ожидаемый результат: `145 passed`.

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

## MULTI-SOURCE ПОИСК ОПЛАЧИВАЕМЫХ ЗАДАЧ (`--all-sources`)

Поиск оплачиваемых задач не только на Superteam Earn, а сразу по нескольким
независимым источникам. Существующая логика Superteam при этом не меняется:
она доступна и как отдельный прогон (`python -m superteam_agent`), и как один из
источников multi-source поиска.

```powershell
.\.venv\Scripts\Activate.ps1
python -m superteam_agent --all-sources                                  # все источники
python -m superteam_agent --all-sources --sources github,opire           # только выбранные
python -m superteam_agent --all-sources --per-source-limit 10            # лимит на источник
```

Сводный отчёт: `bounty_results.json` (секреты вырезаются).

### Источники и их фактический статус

| Источник | Что даёт | Чем подтверждается первоисточник |
| --- | --- | --- |
| `superteam` | Agent API + публичная лента + карточка | существующая логика проекта (карточка = истина) |
| `github` | GitHub Search API: `label:bounty`, `label:"💎 Bounty"`, `bounty in:title`, USDC-варианты | конкретный issue (state/assignee/PR/claimed/paid) |
| `bountybureau` | `https://bountybureau.com/api/bounties` (certified: tier/score/status/payout) | конкретный issue из записи (`owner/repo#number`) |
| `opire` | `https://api.opire.dev/rewards` (пагинация по 30, поле `url` → GitHub issue) | конкретный issue из `url` |
| `warpspeed` | — (проверено: `warpspeed.xyz` продаётся как домен, `warpspeed.dev` — парковка) | `NOT_FOUND`, доказательства в `diagnostics.probes` |
| `openbounty` | — (проверено: `openbounty.xyz`/`.com`/`openbounties.com` — парковка, `openbounty.dev` — нет DNS) | `NOT_FOUND`, доказательства в `diagnostics.probes` |

Статус каждого источника пишется честно: `OK` / `EMPTY` / `PARTIAL` / `ERROR` /
`NOT_FOUND` + причина. Недоступный источник не «дорисовывается»: `discovered = 0`.

### КРИТИЧЕСКОЕ ПРАВИЛО: агрегатор — не доказательство

Каждая найденная задача проверяется по ПЕРВОИСТОЧНИКУ — конкретному GitHub issue
или конкретной странице bounty. Подтверждается:

* issue действительно `open` (и не `state_reason=not_planned`, не `locked`);
* нет assignee (задача не закреплена за исполнителем);
* нет merge/закрытого PR, ссылающегося на issue (bounty фактически отработан);
* нет признаков `claimed`/`paid`/`rewarded` в комментариях, labels и timeline;
* есть реальная сумма награды (`labels` → `title` → `body` → bounty-комментарии
  платформ вида «A bounty of $5000 has been created…»);
* issue не является постом-агрегатором (`[radar]`, «Bounty Alert», «N new
  opportunities found»).

Как это выглядит в коде: `sources/*.py` только ОБНАРУЖИВАЮТ задачи,
`core/verification.py` проверяет первоисточник, `core/filters.py` применяет
политику, `core/ranking.py` ранжирует. Ошибка одного источника не останавливает
поиск: адаптеры запускаются параллельно, ошибка превращается в `ERROR` + причина.

---

### Жёсткий финансовый фильтр

Задача исключается, если для ОБЯЗАТЕЛЬНОЙ части нужны деньги исполнителя:
свои USDC/USDT/SOL, депозит, пополнение баланса, покупка токенов, свой gas,
реальные сделки, mandatory real mainnet trading. «Sponsored Free Lane»,
refund, reimbursement и бонус за бесплатный путь это НЕ отменяют
(реализовано в существующем `risk.py`, повторно используется без изменений).

Разрешено: testnet, devnet, sandbox, mock, simulated/paper trading, бесплатные API,
локальное окружение, тестовые токены без ценности.

Дополнительно (строже, чем раньше): если из текста НЕ видно, нужны ли свои деньги
(описание короче 80 символов или совпадает с заголовком), ставится
`financial_risk = UNKNOWN`, и задача не попадает в recommended до ручной проверки.

### Регион

* `Russia excluded` (явный запрет или санкционные формулировки) → `agent_compatible = false`;
* ограничение конкретными странами → `Restricted`, в top не попадает;
* явное `worldwide`/`anywhere`/`open to everyone` → `Global`;
* регион не указан → `UNKNOWN` и **НЕ считается автоматически подходящим**:
  задача уходит в `needs_manual_check`.

Ослабить последнее правило можно одним флагом в `superteam_agent/config.py`:
`ALLOW_UNKNOWN_REGION_IN_TOP = True`. Аналогичные флаги есть для неизвестного и
MEDIUM финансового риска.

### Что нужно для награды

`reward_amount` + `reward_currency` + `payment_method` + `payment_type`
(`CRYPTO` / `FIAT` / `UNKNOWN`). Задачи вида «paid bounty» без суммы исключаются
(`NO_CONFIRMED_REWARD`). Маленькие bounty ($1–25) не отбрасываются.

### Результат: `bounty_results.json`

```json
{
  "generated_at": "2026-09-15T07:09:44Z",
  "sources": { "github": { "source_status": "OK", "discovered": 31, "verified_open": 6, "kept": 10, "reason": "", "diagnostics": {}, "errors": [] } },
  "counts": { "all_verified": 11, "top_agent_compatible": 0, "top_human_only": 0, "secondary_candidates": 0, "needs_manual_check": 5, "excluded": 35 },
  "all_verified": [ { "source": "...", "title": "...", "url": "...", "status": "OPEN", "bounty_status": "AVAILABLE", "reward_amount": 50, "reward_currency": "USD", "payment_method": "...", "payment_type": "FIAT", "financial_risk": "LOW", "region": "UNKNOWN", "difficulty": "MEDIUM", "estimated_time": "UNKNOWN", "tech_stack": [], "beginner_friendly": false, "agent_compatible": false, "exclusion_reason": "", "verified_at": "..." } ],
  "top_agent_compatible": [],
  "top_human_only": [],
  "secondary_candidates": [],
  "needs_manual_check": [],
  "excluded": [ { "title": "...", "url": "...", "source": "...", "exclusion_reason": "CLOSED", "financial_risk": "LOW", "region": "UNKNOWN", "verified_status": "CLOSED" } ]
}
```

* `all_verified` — задачи, открытость которых подтверждена первоисточником
  (полный контракт полей из задания);
* `top_agent_compatible` — прошли все жёсткие фильтры и посильны агенту;
* `top_human_only` — открытые и оплачиваемые, но не для агентской подачи;
* `secondary_candidates` — сложные (HARD), но потенциально стоящие задачи;
* `needs_manual_check` — неизвестен финансовый риск / регион / стек;
* `excluded` — всё остальное, с причиной (для аудита; задачи не удаляются).

Пустой `top_agent_compatible` — нормальный результат: лучше пустой список, чем
сомнительные задачи.

### Ранжирование (порядок из задания)

1. crypto-выплата → 2. отсутствие финансового риска → 3. подтверждённая
открытость → 4. beginner-friendly → 5. маленькая/простая задача → 6. размер
награды (log-шкала) → 7. global / Russia allowed. Балл и факторы
(`rank_score`, `ranking_factors`) пишутся в отчёт.

### Логи

```
[DISCOVERED] github: найдено 31, подтверждено открытыми 6
[VERIFYING]  github: проверено по первоисточнику 10 записей (source_status=OK)
[VERIFIED OPEN] https://github.com/.../issues/337
[EXCLUDED][CLOSED] https://github.com/.../issues/12 — CLOSED
[EXCLUDED][REGION] https://superteam.fun/earn/listing/... — REGION_RESTRICTED
[EXCLUDED][FINANCIAL RISK] https://github.com/.../issues/99 — REAL_FINANCIAL_ACTIVITY_REQUIRED
[EXCLUDED][CLAIMED] / [EXCLUDED][ASSIGNED] / [EXCLUDED][PR_LINKED] / [EXCLUDED][NO_REWARD]
[RECOMMENDED] https://github.com/.../issues/337
```

### Ограничения (честно)

* `warpSpeed Bounties` и `OpenBounty` по проверенным адресам сейчас не являются
  рабочими bounty-платформами — источники возвращают `NOT_FOUND` с доказательствами;
* регион в GitHub-issue указывается редко, поэтому при строгом режиме почти все
  задачи попадают в `needs_manual_check`;
* формулировки-отрицания в найденном анализаторе риска не всегда распознаются
  («no spending of your own funds» может быть прочитано как требование своих
  средств): выбран консервативный вариант — лучше исключить, чем включить;
* без `GITHUB_TOKEN` GitHub API отдаёт 60 запросов/час, поэтому проверяется
  меньше задач (`GITHUB_MAX_VERIFICATIONS`).

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
* финальная eligibility-фильтрация TOP (`is_agent_compatible()`): в
  `=== TOP AGENT-COMPATIBLE ===` попадают только `VERIFIED_OPEN` + `CANDIDATE` +
  `ELIGIBLE` + `AGENT_ONLY`/`AGENT_ALLOWED` + без флагов `requires_*` + без
  `financial_risk = HIGH`; `REGION_RESTRICTED` → `=== EXCLUDED: REGION ===`
  (`exclusion_reason = REGION_INELIGIBLE`), `UNKNOWN` → `=== MANUAL ELIGIBILITY CHECK ===`;
* разделы `=== TOP OPPORTUNITIES ===` (до 3), `=== TOP AGENT-COMPATIBLE ===`,
  `=== TOP HUMAN-ONLY ===`, `=== EXCLUDED: REGION ===`,
  `=== EXCLUDED: FINANCIAL RISK ===`, `=== EXCLUDED: HUMAN ONLY ===`,
  `=== MANUAL ELIGIBILITY CHECK ===` и полный `=== VERIFIED OPEN ===`;
* в `superteam_results.json` добавлены `top_agent_compatible` и `top_human_only`.

Этап 5 (реализован) — multi-source поиск оплачиваемых задач (см. раздел
«MULTI-SOURCE ПОИСК ОПЛАЧИВАЕМЫХ ЗАДАЧ» выше):

* независимые адаптеры источников `superteam` / `github` / `bountybureau` /
  `opire` / `warpspeed` / `openbounty` (`python -m superteam_agent --all-sources`);
* обязательная проверка ПЕРВОИСТОЧНИКА для каждой задачи (GitHub issue или
  страница bounty): open/closed, assignee, связанные PR, claimed/paid, сумма награды;
* дедупликация одной задачи из разных источников + приоритет источников;
* жёсткий финансовый фильтр (в т.ч. `financial_risk = UNKNOWN` — ручная проверка),
  региональный фильтр с `Russia excluded`, запрет «paid bounty» без суммы;
* разделы `top_agent_compatible` / `top_human_only` / `needs_manual_check` /
  `secondary_candidates` / `excluded` в `bounty_results.json`;
* честные статусы источников `OK` / `EMPTY` / `PARTIAL` / `ERROR` / `NOT_FOUND`
  (warpSpeed и OpenBounty по проверенным адресам не существуют как платформы).

Этап 6 (реализован) — полноценная двухэтапная проверка (discovery → verification):

* единая модель статусов: `VERIFIED_OPEN` / `VERIFIED_EXPIRED` / `VERIFIED_CLOSED` /
  `VERIFIED_WINNER_ANNOUNCED` / `VERIFIED_HUMAN_ONLY` / `UNKNOWN` (старые имена — алиасы);
* карточка «open» без найденного deadline больше не становится `VERIFIED_OPEN`;
* human-only определяется по карточке (`agentAccess=HUMAN_ONLY`) → `VERIFIED_HUMAN_ONLY`;
  отсутствие данных о agent access → `UNKNOWN` + `agent_access_unknown = true`;
* debug/evidence-поля `verified_*` + `verification_url`/`verification_timestamp`/`evidence`;
* список `verified_open_listings` (никаких `UNKNOWN`);
* TTL-кэш проверки карточек (`SUPERTEAM_VERIFICATION_CACHE_TTL`);
* разделы `=== VERIFIED OPEN ===`, `=== EXCLUDED ===`,
  `=== UNKNOWN / VERIFICATION FAILED ===`, `=== STATISTICS ===`;
* исключённая задача больше не может иметь приоритет выше `EXCLUDED`.

Этап 7 (реализован) — пользовательское представление результатов:

* основной результат — Excel-отчёт `superteam_report.xlsx` (openpyxl) с листами
  `SUMMARY` / `AVAILABLE` / `EXCLUDED` / `UNKNOWN`; на `AVAILABLE` попадают только
  задания, прошедшие ВСЕ существующие фильтры (источник — `is_verified_open_listing()`);
* настоящие гиперссылки `Open card` → `card_url` (длинные URL в ячейках не выводятся);
* нормализация причин в короткий человеческий текст (технические причины остаются в JSON);
* компактная консоль (без URL и без списка исключённых), `--report` без обращения к сайту;
* `superteam_report.md` стал компактным Markdown-summary, JSON и кэш не изменены.

Этап 8 (план, по желанию) — не реализовано:

* подготовка черновика submission (по-прежнему **запрещено**);
* история прогонов и сравнение изменений между запусками;
* уведомления о новых подходящих заданиях (в т.ч. слежение за конкретным issue).

Важно: скрипт ничего не изменяет на Superteam — только читает данные (Agent API),
публичную ленту и страницы карточек. Submission и авто-подача заявок не реализованы.

