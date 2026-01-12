# Project Standards & Agent Instructions

This is the ad server for EthicalAds.
It is built with Django and Python.


## 1. Project Overview

- **Language:** Python
- **Framework:** Django
- **Frontend:** Bootstrap + Knockout.js
- **Other Tools:**
  - `uv` (Python Version Manager)
  - `ruff` (Linting/Formatting)
  - `pre-commit` (Git Hooks, runs ruff)
  - `tox` (Testing)

Versions of Python, Django, and other Python dependencies are defined in `pyproject.toml`.

### 1.1 Project Structure

- `adserver/`: The core application handling ad serving and dashboards for publishers and advertisers.
- `config/`: Django project settings and project level configuration.
- `assets`: Frontend assets for the adserver.


## 2. Coding Style & Linting

All code must adhere to the rules defined in `pyproject.toml`.
This typically adheres to the PEP 8 style guide.

Before finalizing any code change, run: `uv run pre-commit run --all-files`.
This will ensure code is formatted and linted and that all imports are sorted.

Imports should go at the top of the file, after any docstrings unless there is a very good reason to do otherwise.


## 3. Testing Procedures

Run `tox` to run the test suite.
This verifies the code style and linting and runs the full test suite.
The test suite verifies that there are no missing migrations
and that test coverage is above the threshold defined in `pyproject.toml.

Every feature or bug fix must include a corresponding test case in the Django app's `tests/` directory (eg. `adserver/tests/test_*.py`).
Typically there is one class per feature, with multiple test methods.
A single test file may contain multiple classes for logical sections (eg. `test_utils.py` tests `utils.py`).


## 4. Django Development Patterns

- **Migrations:** After modifying `models.py`, you must run `uv run python manage.py makemigrations` and include the migration files in the PR. Migrations should be named appropriately and include a description of the changes made.
- **Logic Placement:** Keep views thin if possible. Place business logic in `services.py` or within Model methods where appropriate.
- **Environment Variables:** Use a `.env` file for local development. Never hardcode secrets. `.envs/local/django.sample` is a sample environment file checked into source control. `.envs/local/django` is used for local development secrets and is gitignored.
- **Translations:** Use Django's translation system for any text that should be translatable. Use the `gettext` function for any text that sho
uld be translatable. Use the `gettext_lazy` function for any text that should be translatable in a lazy manner. These are usually imported as
follows: `from django.utils.translation import gettext as _`.


## 5. Agent Workflow Instructions

1. **Self-Correction & Context:** Always read this `AGENTS.md` file at the start of a session. It is the source of truth for project standards.
2. **Plan:** Before writing code, create a task list and plan to document your approach. State which models/views will be affected.
3. **Execute:** Write the code according to the styles above.
4. **Verify:** You MUST run the `tox` command in the integrated terminal before declaring a task "Done." Ensure test coverage remains above the threshold defined in `pyproject.toml`.


## 6. Common Pitfalls

- **Missing Migrations:** Always run `uv run python manage.py makemigrations` after model changes.
- **Coverage Drops:** The test suite (`tox`) and CI will fail if coverage drops below the threshold defined in `pyproject.toml`. Check `htmlcov/` if unsure where lines are missed.
- **Hardcoded Secrets:** Never add secrets to settings or code. Use `.env`.
- **Pre-commit Failures:** If `ruff` or `isort` fail, the commit will be blocked. Run `uv run pre-commit run --all-files` to fix formatting automatically.
