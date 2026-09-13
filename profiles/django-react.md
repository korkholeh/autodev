# Profile: Django/DRF backend with a separate React frontend

## Layout

```
backend/
  manage.py, config/, apps/<app>/{models,serializers,views,urls,services,selectors,tasks}.py
  apps/<app>/tests/
frontend/
  src/{routes,features,components,api}/ , vite.config.ts, package.json
e2e/                    specs that drive the browser across both, plans, support library
docs/dev, docs/user
```

The two halves deploy separately. That seam is the most expensive thing in this stack: both suites can be green
while the product is broken, because nothing tests the contract between them.

## Commands

| Key | Command |
|---|---|
| install | `uv sync` in `backend/`, `npm ci` in `frontend/` |
| build | `npm run build` in `frontend/` |
| run | `python manage.py runserver 8000` and `npm run dev` (port 5173) |
| test | both halves, from the root: `python backend/manage.py test && npm --prefix frontend test -- --run` |
| lint | `ruff check backend` and `npm --prefix frontend run lint` |
| format | `ruff format backend` and `npm --prefix frontend run format` |
| e2e up | start the backend (migrated and seeded) and the frontend dev server |
| e2e | `pytest e2e -q` (pytest-playwright) |
| e2e down | stop both |

## The API contract

- Generate an OpenAPI schema from DRF (`drf-spectacular`) and commit it. A diff in that file is the review's signal
  that the contract changed.
- Generate the frontend's client and types from that schema rather than hand-writing them; a renamed field then
  fails the frontend build instead of failing in production.
- Removing or renaming a field is expand → migrate consumers → contract, across two deploys. Never in one.
- Pin the API under a version prefix (`/api/v1/`) from phase 1.

## End-to-end

Drive a real browser against both surfaces. Both are **required** surfaces — if either is down the run fails with
the command that starts it, rather than skipping.

Cases this stack specifically needs: sign-in and session/token refresh; a page that loads data from the API and its
empty, loading, and error states; a form whose server-side validation errors must appear on the right fields; a role
that must be refused, asserted as a visible refusal rather than a hidden button; and a deep link into a page that
requires auth, which must survive the round trip through the login screen.

Seed through a backend management command; read one-time values (an emailed code, a generated link) through a
backend-provided test channel, never by querying the database from the spec.

## Pitfalls

- Two hostnames that are not interchangeable to a browser (`localhost` vs `127.0.0.1` vs a `.local` name) break
  cookies and CORS silently. Derive one origin per surface and reuse it everywhere.
- CORS and CSRF settings that work in dev and fail behind a proxy: test the deployed configuration shape.
- Serializer-level permission checks are not view-level permission checks. Assert refusal at the endpoint.
- A frontend that swallows a 4xx into a generic "something went wrong" hides real bugs from e2e. Surface the message.
