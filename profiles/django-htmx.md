# Profile: Django with server-rendered templates and htmx

## Layout

```
manage.py
config/ (or <project>/)   settings split by environment, urls.py, asgi/wsgi
apps/<app>/              models.py, views.py, forms.py, urls.py, services.py, selectors.py, templates/<app>/
apps/<app>/tests/        unit and view tests
templates/               base.html and shared partials
static/
e2e/                     browser specs + plans (see guides/e2e-authoring.md)
docs/dev, docs/user
```

One app per bounded piece of the domain. Views stay thin: a view validates input, calls a service, renders a
template. Business rules live in `services.py`; queries live in `selectors.py`.

## Commands

| Key | Command |
|---|---|
| install | `uv sync` (or `pip install -r requirements.txt`) |
| build | `python manage.py collectstatic --noinput` |
| run | `python manage.py runserver 0.0.0.0:8000` |
| test | `python manage.py test` (or `pytest -q` with pytest-django) |
| lint | `ruff check .` and `python manage.py check` |
| format | `ruff format .` |
| e2e up | `python manage.py migrate && python manage.py seed_e2e && python manage.py runserver 8001 &` — or the project's compose file |
| e2e | `pytest e2e -q` (pytest-playwright) |
| e2e down | stop the server started by `e2e up` |

Add `makemigrations --check --dry-run` to the lint step: a model change with no migration must fail the build.

## htmx specifics

- Every htmx endpoint returns a **fragment**, and the same URL should return a full page on a normal request where
  that makes sense. Decide the convention once and put it in `docs/dev/architecture.md`.
- Name the swap target and the trigger explicitly in the template; avoid relying on the default swap.
- Errors must return a fragment the user can see — an HTTP 400 with an empty body swaps nothing and looks like a
  frozen button.
- CSRF: htmx needs the token on every non-GET request. Set it once in `base.html` via `hx-headers`.
- Anything that changes data is POST/PUT/DELETE, never GET, even when htmx makes GET convenient.

## End-to-end

Use a browser driver (Playwright) against a server the orchestrator started. Cases worth having in this stack:
a form that fails validation and shows field errors in the swapped fragment; a partial update that leaves the rest
of the page intact; a flow with the browser Back button after several swaps; a permission-refused page for each role;
and a page that must still work with JavaScript disabled if the spec claims progressive enhancement.

Seed data through a management command (`seed_e2e`) so the suite never writes to storage behind the app's back.

## Pitfalls

- `DEBUG=True` hides real 500s behind a pretty page; e2e must run with `DEBUG=False` and real error templates.
- N+1 queries hide in templates. Assert query counts (`assertNumQueries`) on list views.
- A migration that rewrites a large table locks it; state the strategy in the ADR before writing it.
- Permissions on a view are not permissions on a template include — check both.
