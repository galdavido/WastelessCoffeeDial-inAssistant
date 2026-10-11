"""Write the API schema to docs/openapi.json, the committed contract.

The app serves no /openapi.json or /docs (``openapi_url=None``); the schema is
generated here instead and committed, so a change to any request or response
shape is a reviewable diff. tests/test_openapi.py fails until it is
regenerated:

    python -m core.openapi_export
"""

from __future__ import annotations

import json
from pathlib import Path

from .web_server import app

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def render() -> str:
    """The schema as stable text: sorted keys, so the diff shows only changes."""
    return (
        json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def main() -> None:
    with SCHEMA_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render())
    print(f"Wrote {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
