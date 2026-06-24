# StayWallet backend — FastAPI + SQLAlchemy(async) + Alembic.
# Single-stage slim image; psycopg2-binary and asyncpg ship manylinux wheels,
# so no compiler toolchain is needed.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so the layer is cached across code changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# App source (entrypoint, alembic config + versions, the app package).
COPY . .
RUN chmod +x docker/entrypoint.sh

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# On boot: wait for the DB, apply migrations, seed demo data, then serve.
ENTRYPOINT ["./docker/entrypoint.sh"]
