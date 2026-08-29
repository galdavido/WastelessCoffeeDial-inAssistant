# Contributing to Wasteless Coffee Dial-in Assistant (WCDA)

Thanks for your interest in contributing! We welcome bug reports, feature requests, and pull requests.

## Getting Started

1. Fork the repository and clone your fork locally.
2. Create a virtual environment: `python -m venv .venv && source .venv/bin/activate`
3. Install the project with dev tools: `pip install -e '.[dev]'`
4. Enable pre-commit hooks: `pre-commit install`
5. Copy `.env.example` to `.env` and fill it in.
6. Create a feature branch: `git checkout -b feature/your-feature-name`

## Development Workflow

- Lint & format: `ruff check . && ruff format .`
- Type check: `mypy src`
- Run tests: `pytest` (database-backed tests need a running Postgres and `DATABASE_URL`)
- Apply migrations: `alembic upgrade head`
- Run the web server: `python -m core.web_server` (requires `.env` and Postgres)
- Schema changes go through Alembic: `alembic revision --autogenerate -m "..."`

## Submitting Changes

1. Write clean, idiomatic Python with type hints where applicable.
2. Add or update tests for new features or bug fixes.
3. Ensure all checks pass locally before pushing.
4. Write descriptive commit messages (e.g., `fix: handle missing equipment in RAG search`).
5. Open a pull request with a clear description and link related issues.

## Code Style

- Follow PEP 8 and use Ruff/Black for formatting (pre-commit enforces this).
- Add docstrings to functions and classes.
- Use type hints for function parameters and return values.

## Reporting Issues

- Use GitHub Issues to report bugs or suggest features.
- Include steps to reproduce for bugs.
- Describe the expected vs. actual behavior.

## Questions?

Open a GitHub Discussion or issue—we're happy to help!

Thank you for contributing to Wasteless Coffee Dial-in Assistant (WCDA)!
