FROM python:3.12.16-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
RUN python -m venv /opt/venv
COPY backend/requirements-prod.txt /build/requirements-prod.txt
RUN /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r /build/requirements-prod.txt

FROM python:3.12.16-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    HEALTHCHECK_HOST=localhost \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 10001 muletrace \
    && useradd --system --uid 10001 --gid muletrace --home-dir /app --no-create-home muletrace \
    && mkdir -p /app \
    && chown muletrace:muletrace /app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=muletrace:muletrace backend/app ./app
COPY --chown=muletrace:muletrace backend/alembic ./alembic
COPY --chown=muletrace:muletrace backend/alembic.ini ./alembic.ini
COPY --chown=muletrace:muletrace backend/run.py ./run.py

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os; from urllib.request import Request, urlopen; request = Request('http://127.0.0.1:8000/health/live', headers={'Host': os.environ.get('HEALTHCHECK_HOST', 'localhost')}); response = urlopen(request, timeout=3); raise SystemExit(0 if response.status == 200 else 1)"

ENTRYPOINT ["python", "run.py"]
