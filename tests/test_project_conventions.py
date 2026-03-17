import os
import unittest


class TestProjectConventions(unittest.TestCase):
    def test_env_example_contains_required_keys(self) -> None:
        env_path = os.path.join("config", ".env.example")
        with open(env_path, "r", encoding="utf-8") as file:
            content = file.read()

        required_keys = {
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
            "DATABASE_URL",
            "GEMINI_API_KEY",
            "DISCORD_TOKEN",
        }

        for key in required_keys:
            self.assertIn(f"{key}=", content)

    def test_requirements_are_version_pinned(self) -> None:
        with open("requirements.txt", "r", encoding="utf-8") as file:
            lines = [
                line.strip()
                for line in file
                if line.strip() and not line.startswith("#")
            ]

        unpinned = [line for line in lines if "==" not in line]
        self.assertEqual(unpinned, [])


if __name__ == "__main__":
    unittest.main()
