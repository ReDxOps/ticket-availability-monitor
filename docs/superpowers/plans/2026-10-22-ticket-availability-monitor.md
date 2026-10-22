# Dream Nation 2026 Ticket Availability Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Développer et conteneuriser un service Python autonome 24h/24 surveillant la billetterie officielle See Tickets Resell pour Dream Nation 2026 (Pass 1 Jour Vendredi) afin d'alerter par Telegram dès qu'au moins 1 billet (avec priorité si 2 billets) est disponible.

**Architecture:** Moteur de polling asynchrone utilisant `httpx.AsyncClient` interrogeant l'endpoint public `/api/adverts_search` toutes les 10 secondes. Les états (`AVAILABLE`, `IN_CART`, `SOLD_OUT`, `UNKNOWN`) et les annonces sont suivis en base SQLite pour la déduplication et la détection des retours de panier. Les alertes sont expédiées via l'API Telegram Bot avec liens vérifiés.

**Tech Stack:** Python 3.12+, `httpx`, `pydantic`, `pydantic-settings`, `aiosqlite`, `pytest`, `pytest-asyncio`, `respx`, Docker, Docker Compose.

## Global Constraints
- Surveillance en lecture seule : AUCUN achat, ajout au panier ni paiement automatisé.
- Aucun contournement de CAPTCHA ni mécanisme antibot.
- Backoff exponentiel et respect de `Retry-After` sur 429/5xx.
- Ne jamais interpréter une erreur HTTP, un timeout ou une réponse malformée comme une disponibilité.
- Ne JAMAIS exécuter `git commit` ni `git push` : l'utilisateur gère Git manuellement. Proposer un message de commit concis en anglais à chaque ensemble cohérent.
- Ne pas lancer de tests navigateur ni construire `docker compose` sans demande explicite.

---

### Task 1: Project Environment & Dependency Setup

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: Base project structure and dependencies for testing and runtime.

- [ ] **Step 1: Create `pyproject.toml`**
Declare Python project configuration and dependencies (`httpx`, `pydantic`, `pydantic-settings`, `aiosqlite`, `pytest`, `pytest-asyncio`, `respx`).

- [ ] **Step 2: Create `.env.example`**
Include all required environment variables with documentation and safe default values.

- [ ] **Step 3: Create package marker files `src/__init__.py` and `tests/__init__.py`**

- [ ] **Step 4: Verify Python environment & pytest availability**
Run `pytest --version`.

- [ ] **Step 5: Propose Git commit message**
Proposed commit: `chore: initialize project structure and dependencies`

---

### Task 2: Configuration Module

**Files:**
- Create: `src/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings` class loading configuration from `.env` and environment variables.

- [ ] **Step 1: Write failing test in `tests/test_config.py`**
Test default configuration values, validation of poll interval (>= 5s), category ID, event ID, cutoff date, and telegram settings.

- [ ] **Step 2: Run test to verify it fails**
Run `pytest tests/test_config.py -v`. Expected: ModuleNotFoundError / FAIL.

- [ ] **Step 3: Implement `src/config.py`**
Implement `Settings` with `pydantic-settings` or `pydantic.BaseModel` with validations.

- [ ] **Step 4: Run test to verify it passes**
Run `pytest tests/test_config.py -v`. Expected: PASS.

- [ ] **Step 5: Propose Git commit message**
Proposed commit: `feat: implement configuration module with validation`

---

### Task 3: Domain Models & Availability State

**Files:**
- Create: `src/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `AvailabilityState(str, Enum)`: `AVAILABLE`, `IN_CART`, `SOLD_OUT`, `UNKNOWN`
  - `TicketModel`: id, resale_value_cents, purchase_fees_cents, total_price_cents, product_name
  - `AdvertModel`: id, status, dynamic_status, nb_available, nb_cart, min_price_cents, severability, tickets, state
  - `CategorySummary`: category_id, total_items, available_count, in_cart_count

- [ ] **Step 1: Write failing test in `tests/test_models.py`**
Test state evaluation logic:
- `nbAvailableTickets > 0 and nbCartTickets == 0` -> `AVAILABLE`
- `nbAvailableTickets > 0 and nbCartTickets >= nbAvailableTickets` -> `IN_CART`
- `nbAvailableTickets == 0` -> `SOLD_OUT`
- calculation of prices in EUR (`total_price_eur`).

- [ ] **Step 2: Run test to verify it fails**
Run `pytest tests/test_models.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `src/models.py`**
Define typed models and state resolution helpers.

- [ ] **Step 4: Run test to verify it passes**
Run `pytest tests/test_models.py -v`. Expected: PASS.

- [ ] **Step 5: Propose Git commit message**
Proposed commit: `feat: add domain models and availability state evaluation`

---

### Task 4: SQLite Persistence Layer

**Files:**
- Create: `src/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `DatabaseManager`:
    - `init_db()`
    - `get_advert_state(advert_id: int) -> Optional[dict]`
    - `record_advert_state(advert: AdvertModel) -> Tuple[bool, Optional[str]]` (returns (has_changed, previous_state))
    - `mark_advert_sold_out(advert_id: int)`
    - `log_event(event_type: str, message: str, payload: dict = None)`
    - `is_notification_duplicate(advert_id: int, state: str) -> bool`
    - `record_notification_sent(advert_id: int, state: str)`

- [ ] **Step 1: Write failing test in `tests/test_db.py`**
Test table creation, insert/update advert state, transition detection (`IN_CART` -> `AVAILABLE`), and notification deduplication.

- [ ] **Step 2: Run test to verify it fails**
Run `pytest tests/test_db.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `src/db.py`**
Use `aiosqlite` with schema migrations, indexing on `advert_id`, and transaction handling.

- [ ] **Step 4: Run test to verify it passes**
Run `pytest tests/test_db.py -v`. Expected: PASS.

- [ ] **Step 5: Propose Git commit message**
Proposed commit: `feat: implement SQLite persistence and state history tracking`

---

### Task 5: See Tickets API Client with Backoff

**Files:**
- Create: `src/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Produces:
  - `SeeTicketsClient`:
    - `fetch_adverts(category_id: int) -> Tuple[AvailabilityState, List[AdvertModel], Optional[str]]`
    - `fetch_category_overview(event_id: int) -> Dict[int, int]`
    - Exponential backoff on 429, 403, 5xx with `Retry-After` parsing.
    - Graceful conversion of timeouts and invalid JSON to `UNKNOWN`.

- [ ] **Step 1: Write failing test in `tests/test_client.py`**
Use `respx` to mock:
- 200 OK with adverts (available & in-cart)
- 200 OK with empty hydra collection
- 429 Too Many Requests with `Retry-After: 5`
- 500 Internal Server Error
- Read timeout
- Malformed non-JSON payload

- [ ] **Step 2: Run test to verify it fails**
Run `pytest tests/test_client.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `src/client.py`**
Implement HTTP/2 async client, backoff logic, and parser into `AdvertModel`.

- [ ] **Step 4: Run test to verify it passes**
Run `pytest tests/test_client.py -v`. Expected: PASS.

- [ ] **Step 5: Propose Git commit message**
Proposed commit: `feat: implement resilient See Tickets HTTP client`

---

### Task 6: Telegram Notifier Service & CLI Test Script

**Files:**
- Create: `src/notifier.py`
- Create: `scripts/test_notification.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Produces:
  - `TelegramNotifier`:
    - `send_availability_alert(advert: AdvertModel, is_cart_return: bool = False) -> bool`
    - `send_technical_alert(title: str, details: str) -> bool`
    - `send_test_message() -> bool`

- [ ] **Step 1: Write failing test in `tests/test_notifier.py`**
Verify message formatting:
- Event and Date formatting
- Priority banner for >= 2 tickets
- Direct verified purchase link
- Cart return badge
- Technical alert formatting
- Mocked Telegram API response

- [ ] **Step 2: Run test to verify it fails**
Run `pytest tests/test_notifier.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `src/notifier.py` and `scripts/test_notification.py`**
HTML-formatted Telegram dispatcher with error handling.

- [ ] **Step 4: Run test to verify it passes**
Run `pytest tests/test_notifier.py -v`. Expected: PASS.

- [ ] **Step 5: Propose Git commit message**
Proposed commit: `feat: implement Telegram notification service and test script`

---

### Task 7: Core Monitoring Engine & State Machine

**Files:**
- Create: `src/monitor.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Produces:
  - `TicketMonitor`:
    - `poll_once() -> MonitorCycleResult`
    - `run()`: continuous polling loop with graceful signal handling and cutoff check.

- [ ] **Step 1: Write failing test in `tests/test_monitor.py`**
Test end-to-end cycle scenarios:
1. Cycle 0: No ticket available (`SOLD_OUT`) -> no notification.
2. Cycle 1: 1 ticket available (`AVAILABLE`) -> 1 notification sent.
3. Cycle 2: Same 1 ticket still available -> NO duplicate notification.
4. Cycle 3: 2 tickets available -> priority notification sent.
5. Cycle 4: Ticket moves to cart (`IN_CART`) -> state updated in DB, no false alert.
6. Cycle 5: Ticket released from cart (`IN_CART` -> `AVAILABLE`) -> cart return notification sent!
7. Cycle 6: HTTP 500 error -> `UNKNOWN` state recorded, consecutive errors incremented, no false alert.
8. Cycle 7: Prolonged failure -> technical alert sent.

- [ ] **Step 2: Run test to verify it fails**
Run `pytest tests/test_monitor.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement `src/monitor.py`**
Wire database, client, and notifier in an asynchronous polling loop.

- [ ] **Step 4: Run test to verify it passes**
Run `pytest tests/test_monitor.py -v`. Expected: PASS.

- [ ] **Step 5: Propose Git commit message**
Proposed commit: `feat: implement ticket availability monitor engine`

---

### Task 8: Docker Packaging & Operational Documentation

**Files:**
- Create: `Dockerfile`
- Create: `compose.yaml`
- Create: `README.md`

**Interfaces:**
- Produces: Ready-to-deploy Linux Docker Compose setup with non-root user, persistent volume for SQLite, healthcheck, and documentation.

- [ ] **Step 1: Create `Dockerfile`**
Multi-stage or lean Python 3.12-slim container with non-root security user and healthcheck script.

- [ ] **Step 2: Create `compose.yaml`**
Service definition with `restart: unless-stopped`, env file binding, and local volume mapping `./data:/app/data`.

- [ ] **Step 3: Create `README.md`**
Detailed documentation with installation steps, test commands, log inspection, Docker run commands, and troubleshooting.

- [ ] **Step 4: Propose Git commit message**
Proposed commit: `chore: add Dockerfile, compose configuration, and documentation`
