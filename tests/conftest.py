"""Shared test setup.

Provides dummy connection/API settings so modules that read them at import
time don't blow up. Tests that actually touch the database require a running
Postgres and a real DATABASE_URL (see the CI workflow).
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg2://tester:tester@localhost:5432/wcda_test"
)
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
os.environ.setdefault("WCDA_HOST", "127.0.0.1")
# Uploaded bag photos from the API tests land here, not in the repo's data/.
os.environ.setdefault("LOG_IMAGES_DIR", tempfile.mkdtemp(prefix="wcda-test-images-"))
