
# Refactor Plan — `unfoldingWord/fred-zulip-bot` (Target: Python 3.13)

**Goal:** Align `fred-zulip-bot` with solid Python hygiene (SRP/DRY), borrow proven patterns from **Zion** (routing/layering) and **BT Servant** (TinyDB, LangGraph, intent rigor), maintain behavior parity, and add tests + CI gates. This expands the earlier plan with concrete tasks, file paths, class/function signatures, acceptance criteria, and PR choreography.

> Scope principle: *small, safe PRs* with parity preserved at each step. Feature flags + branch isolation for risky changes.

---

## Architectural Tenets

- **SRP by layers:** routes → services → adapters → core (models/config/logging).
- **Dependency inversion:** `app.state.services` acts as the service container; anything touching IO sits behind adapters.
- **Portability:** avoid Unix-only deps; use environment markers and guards.
- **Safety-first SQL:** read-only, one-statement, denylist + allowlist.
- **Observability:** structured logging, intent classification logs, DB timings, correlation IDs.
- **Testability:** pure functions where possible; side-effects at boundaries; easy to mock.

---

## Repository Layout (Target)

```
fred_zulip_bot/
  apps/api/app.py                # create_app(), register_routes(app)
  apps/api/routes/chat.py        # POST /chat
  apps/api/routes/health.py      # GET /healthz, /ready
  orchestration/graph.py         # minimal LangGraph for 3 intents
  services/chat_service.py       # process flow split into helpers
  services/intent_service.py     # classify + dispatch, enum + examples
  services/sql_service.py        # SQL guard + summarize helpers
  adapters/zulip_client.py       # Zulip wrapper (send)
  adapters/mysql_client.py       # read-only MySQL client (submit_query)
  adapters/history_repo/
    base.py                      # HistoryRepository protocol
    tinydb_repo.py               # TinyDB implementation
  core/config.py                 # pydantic-settings for env/paths/urls
  core/logging.py                # logger factory (json, levels)
  core/models.py                 # Pydantic DTOs: ChatRequest, ChatResponse, ZulipMessage
  tests/
    unit/
      test_sql_safety.py
      test_intent_service.py
      test_chat_service.py
    api/
      test_routes_chat.py
      test_routes_health.py
  requirements.txt               # runtime deps
  pyproject.toml                 # ruff/mypy/pytest config (py3.13)
  .pre-commit-config.yaml
  .github/workflows/ci.yml
```

---

## Phase 0 — Unblock Windows & Hygiene (`chore/py313-tooling`)

**Problems addressed**
- `sh` imports `fcntl` on Windows → install break.
- Missing common dev tooling.

**Changes**
1. **requirements.txt**
   ```ini
   # Runtime
   fastapi==0.115.0
   uvicorn[standard]==0.30.6
   pydantic==2.9.2
   pydantic-settings==2.5.2
   tinydb==4.8.0
   # mysql connector (read-only usage)
   mysqlclient==2.2.4 ; platform_system != "Windows"
   pymysql==1.1.1     ; platform_system == "Windows"

   # Guard or remove sh:
   sh==1.14.3 ; platform_system != "Windows"
   ```
   - If `sh` is unused, **delete it** entirely.
2. **Dev tools (in `requirements-dev.txt` or extras)**
   ```ini
   pytest==8.3.3
   pytest-cov==5.0.0
   ruff==0.6.9
   mypy==1.11.2
   pre-commit==4.0.1
   ```
3. **`pyproject.toml` (key excerpts)**
   ```toml
   [project]
   name = "fred-zulip-bot"
   requires-python = ">=3.13"

   [tool.ruff]
   line-length = 100
   target-version = "py313"
   lint.select = ["E","F","I","B","UP","S","PGH","RUF"]
   lint.ignore = ["E203","E501"]
   format = { quote-style = "double" }

   [tool.mypy]
   python_version = "3.13"
   strict = true
   warn_unused_ignores = true
   disallow_untyped_defs = true

   [tool.pytest.ini_options]
   addopts = "-q --cov=fred_zulip_bot --cov-report=term-missing"
   ```

4. **`.pre-commit-config.yaml` (key hooks)**
   ```yaml
   repos:
     - repo: https://github.com/astral-sh/ruff-pre-commit
       rev: v0.6.9
       hooks:
         - id: ruff
           args: [--fix]
         - id: ruff-format
     - repo: https://github.com/pre-commit/mirrors-mypy
       rev: v1.11.2
       hooks:
         - id: mypy
   ```

5. **CI (`.github/workflows/ci.yml`)**
   ```yaml
   name: ci
   on: [push, pull_request]
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: "3.13"
         - run: python -m pip install -U pip
         - run: pip install -r requirements.txt
         - run: pip install -r requirements-dev.txt
         - run: ruff check .
         - run: ruff format --check .
         - run: mypy fred_zulip_bot
         - run: pytest
   ```

**Acceptance**
- Fresh install succeeds on Windows & Linux.
- `ruff`, `mypy`, `pytest` all pass locally and in CI.

**Risk Mitigation**
- If dropping `sh` reveals hidden usage, re-introduce behind platform guards or replace call sites with `subprocess.run` wrapped in a small util.

---

## Phase 1 — App Skeleton & Routing (`refactor/app-factory`)

**Goals**
- Move to app factory pattern.
- Thin route modules, Zion-style registration, health endpoints.

**New code**
- `apps/api/app.py`
  ```py
  from fastapi import FastAPI
  from .routes.chat import register_chat_routes
  from .routes.health import register_health_routes
  from ....core.logging import make_logger
  from ....core.config import Settings, get_settings

  def create_app(settings: Settings | None = None) -> FastAPI:
      settings = settings or get_settings()
      app = FastAPI(title="fred-zulip-bot")
      # service container stub; filled in Phase 2
      app.state.services = {}
      app.state.logger = make_logger(settings)
      register_chat_routes(app)
      register_health_routes(app)
      return app
  ```
- `apps/api/routes/chat.py`
  ```py
  from fastapi import APIRouter, FastAPI
  from ....core.models import ChatRequest, ChatResponse

  router = APIRouter()

  @router.post("/chat", response_model=ChatResponse)
  async def chat_endpoint(req: ChatRequest) -> ChatResponse:
      # temporary shim calling existing logic (Phase 2 extracts services)
      from ....services.chat_service import process_user_message  # local import to avoid cycles
      return await process_user_message(req)

  def register_chat_routes(app: FastAPI) -> None:
      app.include_router(router)
  ```
- `apps/api/routes/health.py`
  ```py
  from fastapi import APIRouter, FastAPI

  router = APIRouter()

  @router.get("/healthz")
  async def health() -> dict[str, str]:
      return {"status": "ok"}

  @router.get("/ready")
  async def ready() -> dict[str, str]:
      return {"status": "ready"}

  def register_health_routes(app: FastAPI) -> None:
      app.include_router(router)
  ```

**Acceptance**
- `/chat` behavior identical to pre-refactor.
- `/healthz` returns 200 JSON `{status:"ok"}`.

**Notes**
- Keep `main.py` as a thin shim that imports `create_app()` and exposes `uvicorn` factory (`--factory`).

---

## Phase 2 — Split `main.py` into SRP Services (`refactor/services-adapters`)

**Extraction targets**
- `send_zulip_message` → `adapters/zulip_client.py`
  ```py
  class ZulipClient:
      def __init__(self, realm_url: str, email: str, api_key: str):
          ...  # build zulip client

      def send(self, to: str, topic: str, content: str) -> None:
          ...
  ```
- `submit_query` (read-only) → `adapters/mysql_client.py`
  ```py
  class MySqlClient:
      def __init__(self, dsn: str):
          ...

      def select(self, sql: str, params: tuple | None = None) -> list[dict]:
          # Validate via sql_service.is_safe_sql()
          ...
  ```
- History helpers → `adapters/history_repo/tinydb_repo.py`.
- Prompts/constants → `services/intent_service.py` + `services/sql_service.py`.
- Main flow → `services/chat_service.py` (≤ 40–60 LOC helpers).
  ```py
  async def process_user_message(req: ChatRequest) -> ChatResponse: ...
  def determine_intent(text: str) -> IntentType: ...
  async def handle_chatbot(...): ...
  async def handle_other(...): ...
  async def handle_database(...): ...
  ```

**Service container**
- Populate in `create_app()`:
  ```py
  app.state.services = {
      "zulip_client": ZulipClient(...from settings...),
      "history_repo": TinyDbHistoryRepo(...),
      "sql_client": MySqlClient(...),    # optional until DB used
      "llm_client": GeminiClient(...),   # or placeholder
      "logger": make_logger(settings),
  }
  ```

**Acceptance**
- Unit tests for `is_safe_sql` and intent branching.
- Manual parity: identical responses for a sample of prompts.

**Safety**
- Convert any string building to parameterized queries; guard with allowlist and one-statement checks.

---

## Phase 3 — Swap JSON for TinyDB (BT Servant style) (`feat/tinydb-history`)

**Why**
- File-per-user JSON scales poorly; TinyDB provides simple local KV with query by key.

**Changes**
- `adapters/history_repo/base.py`
  ```py
  from typing import Protocol
  class HistoryRepository(Protocol):
      def get(self, email: str) -> list[dict]: ...
      def save(self, email: str, history: list[dict]) -> None: ...
  ```
- `adapters/history_repo/tinydb_repo.py`
  ```py
  class TinyDbHistoryRepo(HistoryRepository):
      def __init__(self, path: str): ...
      def get(self, email: str) -> list[dict]: ...
      def save(self, email: str, history: list[dict]) -> None: ...
  ```
- Remove the legacy file-system adapter and persist exclusively to TinyDB.

**Settings**
- `core/config.py` provides `HISTORY_DB_PATH`.

**Acceptance**
- New writes/read go to TinyDB; file-based storage is removed to keep the surface small.

---

## Phase 4 — Minimal LangGraph Wiring (`feat/langgraph-orchestration`)

**Rationale**
- Transparent orchestration with typed states, easy to add intents later.

**Design**
- `orchestration/graph.py`
  ```py
  from typing import TypedDict
  from ..services.intent_service import classify_intent, IntentType
  from ..core.models import ChatRequest, ChatResponse

  class GraphState(TypedDict):
      request: ChatRequest
      intent: IntentType | None
      sql: str | None
      result: str | None
      response: ChatResponse | None

  # pseudo-code with LangGraph-like structure
  def build_graph(...):
      # nodes: classify_intent → route
      # chatbot → handle_chatbot
      # other   → handle_other
      # database→ validate_sql → run_query → summarize
      ...
  ```

**Feature flag**
- `ENABLE_LANGGRAPH` defaults to `true`; set it to `false` locally when you need to bypass the graph.

**Acceptance**
- With flag off: parity with Phase 2.
- With flag on: same responses for test prompts; node transitions logged.

---

## Phase 5 — Explicit Intent Model (`feat/intent-enum`)

**Changes**
- `services/intent_service.py` gains:
  ```py
  from enum import Enum

  class IntentType(str, Enum):
      database = "database"
      chatbot = "chatbot"
      other = "other"
  ```
- Centralize prompt and examples; expose `classify_intent(text) -> IntentType`.
- `chat_service` dispatches on enum.
- Optional future intents (feature-gated): `SET_RESPONSE_LANGUAGE`, `SET_AGENTIC_STRENGTH`.

**Acceptance**
- Tests for misclassification fallbacks and typed handling.

---

## Phase 6 — Tests, Lint, Types, and CI (`ci/strict-gates`)

**Tests**
- `tests/unit/test_sql_safety.py`: forbidden keywords; multi-statement guard; allowlist OK.
- `tests/unit/test_intent_service.py`: examples map to expected enums.
- `tests/unit/test_chat_service.py`: mock LLM + DB + Zulip; assert dispatch + results.
- `tests/api/test_routes_chat.py`: FastAPI `TestClient` for `/chat` path/happy/sad.
- `tests/api/test_routes_health.py`: `/healthz` and `/ready` return 200.

**Gates**
- pre-commit on changed files: `ruff`, `mypy`, `pytest -q`.
- CI coverage threshold: start at 70%, ratchet up later.

---

## SQL Safety Details

**Allowlist**
- `SELECT` single statement only.

**Denylist**
- Statement separators/comments: `;`, `--`, `/* */`
- Dangerous clauses: `INTO OUTFILE`, `LOAD DATA`
- DDL/DML/privilege verbs: `DROP|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|CALL|CREATE|GRANT|REVOKE`

**Implementation sketch (`services/sql_service.py`)**
```py
import re

DENY = re.compile(r"\b(drop|alter|insert|update|delete|truncate|call|create|grant|revoke)\b", re.I)
DANGEROUS = re.compile(r";|--|/\*|\*/|into\s+outfile|load\s+data", re.I)

def is_safe_sql(sql: str) -> bool:
    s = sql.strip()
    if not s.lower().startswith("select"):
        return False
    if DENY.search(s) or DANGEROUS.search(s):
        return False
    # naive single-statement check
    if s.count(";") > 0:
        return False
    return True
```

---

## Logging & Telemetry

- `core/logging.py` JSON logger with fields: `ts`, `level`, `msg`, `intent`, `user`, `lat_ms`, `db_ms`, `node` (when LangGraph enabled), `corr_id`.
- Inject correlation ID per request (`X-Request-ID` or generated UUID).

---

## Settings (`core/config.py`)

- Pydantic Settings fields (examples):
  ```py
  class Settings(BaseSettings):
      zulip_realm_url: AnyHttpUrl
      zulip_email: EmailStr
      zulip_api_key: str
      mysql_dsn: str | None = None
      history_db_path: str = "./data/history.json"
      enable_langgraph: bool = True
  ```

---

## PR Choreography

1. `chore/py313-tooling` → install/lint/type/test base (no behavior changes).
2. `refactor/app-factory` → app factory + routers; main shim.
3. `refactor/services-adapters` → extract services/adapters with parity.
4. `feat/tinydb-history` → swap to TinyDB only; remove filesystem adapter.
5. `feat/langgraph-orchestration` → graph behind flag.
6. `feat/intent-enum` → typed intents; examples centralized.
7. `ci/strict-gates` → ratchet coverage; enforce gates.

Each PR:
- Title: `Phase N — <summary>`
- Labels: `refactor`, `enhancement`, `ci`, `tech-debt` as applicable.
- Checklist: install OK on Windows, tests added/updated, parity notes, rollback plan.

---

## Commands Cheat Sheet

```bash
# Dev
pre-commit install
uvicorn fred_zulip_bot.apps.api.app:create_app --factory --reload --port 8000

# Quality
ruff check . && ruff format --check . && mypy fred_zulip_bot && pytest -q

# LangGraph toggle
ENABLE_LANGGRAPH=false uvicorn fred_zulip_bot.apps.api.app:create_app --factory --reload --port 8000
```

---

## Rollback & Risk Notes

- LangGraph stays feature-flagged until confidence is high.
- DB access remains read-only; no credentialed write path in container image.
- If Windows import issues reappear, verify platform markers and optional imports.

---

## Future (Optional)

- Add `SET_RESPONSE_LANGUAGE` and `SET_AGENTIC_STRENGTH` intents and handlers (parity with BT Servant).
- Structured metrics export (OpenTelemetry) for intent distributions and latency percentiles.
- Swap TinyDB to SQLite if scale grows; the interface already abstracts it.
