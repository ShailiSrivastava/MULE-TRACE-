import sys, os, importlib.util, importlib.abc

class _WDACGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith("sqlalchemy.") and (fullname.endswith("_cy") or "cyextension" in fullname):
            pkg_dir = os.path.dirname(importlib.util.find_spec("sqlalchemy").origin)
            rel = fullname.replace("sqlalchemy.", "").replace(".", os.sep) + ".py"
            py_path = os.path.join(pkg_dir, rel)
            if os.path.exists(py_path):
                spec = importlib.util.spec_from_file_location(fullname, py_path)
                return spec
        return None

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.meta_path.insert(0, _WDACGuard())
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client
