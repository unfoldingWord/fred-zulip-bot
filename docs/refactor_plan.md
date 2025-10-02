# Refactor Plan — `unfoldingWord/fred-zulip-bot` (Target: Python 3.13)

**Goal:** Align `fred-zulip-bot` with solid Python hygiene (SRP/DRY), borrow proven patterns from **Zion** (routing/layering) and **BT Servant** (TinyDB, LangGraph, intent rigor), maintain behavior parity, and add tests + gates.

---

## Design Tenets
- **Small, single-responsibility functions**; thin routes, testable services, adapters at boundaries.
- **Dependency inversion:** `app.state.services` holds clients; routes/services don’t import globals.
- **Read-only SQL with strict guards**; no concatenation; whitelist-only.
- **Observability:** structured logs; intent/latency/DB timing events.
- **Portable:** avoid Unix-only libs; guard with environment markers when unavoidable.

## Target Layout
```
fred_zulip_bot/
  apps/api/app.py            # create_app(), registers routers
  apps/api/routes/chat.py    # /chat (thin handler)
  apps/api/routes/health.py  # /healthz, /ready
  orchestration/graph.py     # minimal LangGraph for 3 intents
  services/chat_service.py   # process flow split into helpers
  services/intent_service.py # classify + dispatch
  services/sql_service.py    # SQL guard + summary helpers
  adapters/zulip_client.py   # Zulip wrapper
  adapters/mysql_client.py   # read-only MySQL client
  adapters/history_repo/
    base.py
    tinydb_repo.py           # default
    files_repo.py            # legacy adapter (for migration)
  core/config.py             # pydantic-settings
  core/logging.py            # logger factory
  core/models.py             # Pydantic DTOs
  tests/                     # pytest
  pyproject.toml             # ruff/mypy/pytest (py3.13)
  .pre-commit-config.yaml
  .github/workflows/ci.yml
```

## Phases (small, safe PRs)

### Phase 0 — Unblock & Tooling (`chore/py313-tooling`)
- Remove/guard Unix-only `sh` (Windows fcntl break) or drop if unused.
- Add dev deps: `pytest`, `pytest-cov`, `ruff`, `mypy`, `pre-commit`.
- Add `pyproject.toml` (py3.13), `.pre-commit-config.yaml`, CI workflow.

**Acceptance:** clean install on Windows/Linux; `ruff`, `mypy`, `pytest` run; CI green.

---

### Phase 1 — App Factory & Routers (`refactor/app-factory`)
- Introduce `create_app()`; attach `app.state.services` container.
- Move `/chat` to `routes/chat.py`, add `/healthz` in `routes/health.py`.
- Keep behavior parity (handlers call existing logic).

**Acceptance:** `/chat` responses unchanged; `/healthz` 200.

---

### Phase 2 — Services & Adapters (`refactor/services-adapters`)
- Extract: `ZulipClient`, `MySqlClient` (read-only), history `files_repo`.
- Move DTOs to `core/models.py`; split logic into `chat_service`, `intent_service`, `sql_service`.

**Acceptance:** unit tests for SQL guard + intent branching; manual smoke parity.

---

### Phase 3 — TinyDB Migration (`feat/tinydb-history`)
- Add `tinydb_repo.py`; default to TinyDB via settings.
- One-shot migration from `./data/chat_histories/*.json` → TinyDB.

**Acceptance:** migration logs counts; new writes hit TinyDB; legacy adapter retained for fallback.

---

### Phase 4 — Minimal LangGraph (`feat/langgraph-orchestration`)
- `orchestration/graph.py`: `classify_intent → {chatbot|other|database}` nodes calling existing services.
- Feature flag to bypass if issues arise.

**Acceptance:** parity; node transitions covered by tests.

---

### Phase 5 — Explicit Intents (`feat/intent-enum`)
- `IntentType` enum; typed payloads; examples near classifier; `chat_service` dispatches by enum.

**Acceptance:** tests for misclassification fallbacks.

---

### Phase 6 — CI Gates & Coverage (`ci/strict-gates`)
- Enforce `ruff check`, `ruff format --check`, `mypy --strict`, `pytest --cov` (≥70% threshold initial).

**Acceptance:** PRs block on failures; coverage summary in CI.

---

## SQL Safety (initial)
- Allow only `SELECT` (single statement).
- Deny: `;`, `--`, `/* */`, `INTO OUTFILE`, `LOAD DATA`, DDL/DML verbs (`DROP|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|CALL|CREATE|GRANT|REVOKE`).

## Tooling (snippets)

**`pyproject.toml` (3.13)**
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

**`.pre-commit-config.yaml`**
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

**`.github/workflows/ci.yml`**
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
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy fred_zulip_bot
      - run: pytest
```

## Migration Script (JSON → TinyDB)
- Provide `tools/migrate_history_to_tinydb.py` to upsert per-user histories by email.

## Validation Checklist
- Tests pass; lints/types clean; parity manual checks; data migrated; CI green.

## Commands
```bash
pre-commit install
ruff check . && ruff format --check . && mypy fred_zulip_bot && pytest -q
uvicorn fred_zulip_bot.apps.api.app:create_app --factory --reload --port 8000
python tools/migrate_history_to_tinydb.py
```