"""Guards against a few easy-to-regress project conventions."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class TestProjectConventions(unittest.TestCase):
    def test_env_example_contains_required_keys(self) -> None:
        content = (_ROOT / ".env.example").read_text(encoding="utf-8")
        required = {
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "DATABASE_URL",
            "GEMINI_API_KEY",
        }
        for key in required:
            self.assertIn(f"{key}=", content)

    def test_env_example_has_no_real_looking_secret(self) -> None:
        content = (_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertNotIn("AIzaSy", content, "Gemini API key committed to .env.example")

    def test_simulator_is_not_imported_by_production_code(self) -> None:
        """core/sim.py is a test fixture: its taste model is deliberately crude.

        If it ever leaks into a request path, simulated physics starts
        influencing real recommendations.
        """
        offenders = []
        for path in (_ROOT / "src").rglob("*.py"):
            if path.name == "sim.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "import sim" in text or "from .sim" in text or "core.sim" in text:
                offenders.append(str(path.relative_to(_ROOT)))
        self.assertEqual(
            offenders, [], f"production modules importing the simulator: {offenders}"
        )

    def test_engine_core_stays_import_clean_of_the_database(self) -> None:
        """brewing/calibration must import without DATABASE_URL set.

        database.database raises at import time when the URL is missing, so a
        stray import here would drop these modules out of the DB-free test
        path -- which is the only path CI runs on every push.
        """
        import ast

        banned_roots = {"database", "sqlalchemy", "google", "alembic"}
        for module in ("brewing.py", "calibration.py", "sim.py"):
            path = _ROOT / "src" / "core" / module
            if not path.is_file():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertEqual(
                imported & banned_roots,
                set(),
                f"{module} imports {imported & banned_roots}, which would drop it "
                f"out of the DB-free test path",
            )

    def test_runtime_dependencies_are_version_constrained(self) -> None:
        data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        deps = data["project"]["dependencies"]
        self.assertTrue(deps)
        unconstrained = [
            d for d in deps if not any(op in d for op in ("==", ">=", "~=", "<"))
        ]
        self.assertEqual(unconstrained, [])

    def test_requirements_lock_mirrors_pyproject_packages(self) -> None:
        data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        pyproject_pkgs = {_package_name(dep) for dep in data["project"]["dependencies"]}
        lock_lines = [
            line.strip()
            for line in (_ROOT / "requirements.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        lock_pkgs = {_package_name(line) for line in lock_lines}
        self.assertEqual(pyproject_pkgs, lock_pkgs)


def _package_name(spec: str) -> str:
    for sep in ("==", ">=", "~=", "<", ">", "["):
        spec = spec.split(sep)[0]
    return spec.strip().lower()


if __name__ == "__main__":
    unittest.main()
