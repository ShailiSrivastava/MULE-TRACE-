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
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
