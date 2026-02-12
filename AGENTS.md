# Repository Guidelines

## Project Structure & Module Organization
- `app.py` is the primary Flask application entry point, with supporting modules in `*.py` files at the repo root (e.g., `db.py`, `master_player.py`).
- Frontend assets live in `static/` (JS, images) and `less/` (styles). HTML templates are in `templates/`.
- Tests are in `test/` and `test_websocket.py`; database schema files live in `db_schema/`.
- Docs and operational notes are in `docs/`, `README.md`, and `QUEUEING.md`.

## Build, Test, and Development Commands
- `docker compose up --build` starts the full stack (Flask app + Redis + worker) for local development.
- `pip install -r requirements.txt` installs Python dependencies for non-Docker workflows.
- `redis-server` runs the Redis backend needed by the queue and session state.
- `python run.py` starts the Flask app locally on the configured port.
- `pytest` runs the test suite; `tox` runs tests in a managed env (legacy `py27` entry in `tox.ini`).

## Coding Style & Naming Conventions
- Python code uses 4-space indentation and prefers PEP 8 naming (snake_case functions/variables, CapWords classes).
- Keep module-level scripts in the repo root; place web assets in `static/` and templates in `templates/`.
- Avoid adding new formatting or linting tools unless requested; keep changes consistent with existing style.

## Testing Guidelines
- Tests use `pytest`. Name files `test_*.py` and keep test functions prefixed with `test_`.
- For websocket behavior, check `test_websocket.py` for patterns and fixtures.
- Run targeted tests first (e.g., `pytest test/test_auth.py`) before full runs.

## Commit & Pull Request Guidelines
- Recent commits use short, imperative subjects like “Fix …”, “Add …”, or “Document …”.
- Keep commits focused; update changelog or docs only when behavior changes.
- PRs should include: a clear summary, testing notes (`pytest`, `docker compose`), and UI screenshots when frontend changes are visible.

## Configuration & Secrets
- Copy `config.example.yaml` to `local_config.yaml` for local overrides.
- Store OAuth secrets only in local files; do not commit credentials.
- Reference `SECURITY.md` for reporting and disclosure guidance.
