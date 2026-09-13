# Profile: FastAPI backend with a separate React frontend

## Layout

```
backend/
  app/main.py             the ASGI app and router registration
  app/api/v1/             routers, one module per resource
  app/schemas/            pydantic request/response models — the contract
  app/models/             ORM models (SQLAlchemy/SQLModel)
  app/services/           business rules; routers stay thin
  app/db/                 session, migrations (alembic/)
  tests/                  pytest, with httpx.AsyncClient against the app
frontend/
  src/{routes,features,components,api}/ , vite.config.ts, package.json
e2e/                      browser specs across both, plans, support library
docs/dev, docs/user
```

## Commands

| Key | Command |
|---|---|
| install | `uv sync` in `backend/`, `npm ci` in `frontend/` |
| build | `npm run build` in `frontend/` |
| run | `uvicorn app.main:app --reload --port 8000` and `npm run dev` |
| test | `pytest backend -q && npm --prefix frontend test -- --run` |
| lint | `ruff check backend && mypy backend` and `npm --prefix frontend run lint` |
| format | `ruff format backend` and `npm --prefix frontend run format` |
| e2e up | `alembic upgrade head`, seed, start uvicorn and the frontend dev server |
| e2e | `pytest e2e -q` (pytest-playwright) |
| e2e down | stop both |

## The API contract

- The pydantic schemas *are* the contract, and FastAPI publishes them at `/openapi.json`. Commit a snapshot of that
  file and diff it in review — an unintended contract change is then visible.
- Generate the frontend client and types from the schema; do not hand-write them.
- `response_model` on every route: without it, an internal field leaks the moment someone adds it to the ORM model.
- Version the API from phase 1 (`/api/v1/`), and treat removals as expand → migrate → contract across two deploys.

## Async specifics

- Pick sync or async database access once and keep it. Mixing a blocking driver into an async route quietly
  serializes the whole server; that decision belongs in an ADR.
- Background work (`BackgroundTasks`, or a real worker) has no retry semantics by default. If the spec needs the work
  to survive a restart, it needs a queue and an idempotency key — state which in the architecture.
- Test async paths with the app's own async test client, not by hand-rolling an event loop per test.

## End-to-end

Same shape as any split-deploy web product: drive a real browser against both surfaces, both required. Cases worth
having here: auth including token expiry and refresh; a validation error rendered on the correct field (FastAPI's
422 body is nested — the frontend's mapping of it is a real bug source); pagination; a long-running request and its
loading state; and every role the spec names, refused visibly.

Seed through a backend CLI command or a dedicated test-only endpoint that exists only outside production.

## Pitfalls

- Alembic autogenerate misses constraint and enum changes. Read every generated migration before committing it.
- A 422 from pydantic looks nothing like a 400 the frontend expects — fix the mapping once, in one place.
- Dependency-injected auth is easy to forget on a new router; assert refusal on every protected endpoint.
- `--reload` is a development flag only. The operations doc must give the real command with worker counts.
