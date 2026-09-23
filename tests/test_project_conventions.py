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

    def test_bean_delete_handles_every_table_that_references_beans(self) -> None:
        """Adding a table with a link to beans must not make coffees undeletable.

        This is exactly how the recommendations table broke deletion: the
        route cleared the shot logs and then the bean, the new foreign key
        refused, and the coffee could not be removed at all.
        """
        import inspect

        from core import web_routes
        from database.models import Base

        source = inspect.getsource(web_routes)
        start = source.index('@app.delete("/api/logs/{bean_id}")')
        delete_source = source[start : start + 2000]

        referencing = {
            table.name
            for table in Base.metadata.tables.values()
            for fk in table.foreign_keys
            if fk.column.table.name == "beans" and table.name != "beans"
        }
        self.assertIn("dial_in_logs", referencing, "test is not finding the FKs")

        # Model class names are what the route actually queries.
        handled = {
            table.name
            for table in Base.metadata.tables.values()
            for cls in Base.registry.mappers
            if cls.local_table is not None
            and cls.local_table.name == table.name
            and cls.class_.__name__ in delete_source
        }
        missing = referencing - handled
        self.assertEqual(
            missing,
            set(),
            f"tables reference beans but are not handled when deleting one: "
            f"{sorted(missing)} — a coffee with such a row cannot be deleted",
        )

    def test_frontend_javascript_parses(self) -> None:
        """A syntax error in app.js ships a completely blank app.

        There is no build step to catch one, and the Python suite otherwise
        never looks at the frontend. Skipped where node is unavailable; CI
        has it.
        """
        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            self.skipTest("node not available")
        for name in ("app.js", "sw.js"):
            path = _ROOT / "src" / "web" / "static" / name
            result = subprocess.run(
                [node, "--check", str(path)], capture_output=True, text=True
            )
            self.assertEqual(
                result.returncode, 0, f"{name} failed to parse:\n{result.stderr}"
            )

    def test_engine_core_stays_import_clean_of_the_database(self) -> None:
        """brewing/calibration must import without DATABASE_URL set.

        database.database raises at import time when the URL is missing, so a
        stray import here would drop these modules out of the DB-free test
        path -- which is the only path CI runs on every push.
        """
        import ast

        banned_roots = {"database", "sqlalchemy", "google", "alembic"}
        for module in ("brewing.py", "calibration.py"):
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
