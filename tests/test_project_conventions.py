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
