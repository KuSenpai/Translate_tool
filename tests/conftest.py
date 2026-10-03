import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Isolate data/output dirs *before* the app modules read config.
_TMP = Path(tempfile.mkdtemp(prefix="novel-test-"))
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["OUTPUT_DIR"] = str(_TMP / "output")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["TRANSLATE_PROVIDER"] = "mock"

from tests.make_sample import build_book, build_duplicate_book  # noqa: E402


@pytest.fixture(scope="session")
def tmp_root():
    yield _TMP
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def book(tmp_root):
    return build_book(tmp_root / "src" / "book.docx")


@pytest.fixture(scope="session")
def dup_book(tmp_root):
    return build_duplicate_book(tmp_root / "src" / "dup.docx")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)
