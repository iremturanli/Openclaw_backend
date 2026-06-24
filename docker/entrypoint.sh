#!/usr/bin/env sh
# Container boot sequence: wait for Postgres, apply migrations, seed the demo
# data (idempotent), then start the API. Any failure aborts the boot so the
# container is restarted by Docker rather than serving against a half-ready DB.
set -e

# ── Wait for the database ────────────────────────────────────────────────
# compose `depends_on: condition: service_healthy` usually covers this, but a
# short retry makes the image robust when run without that guarantee.
echo "[entrypoint] waiting for the database…"
i=0
until python -c "
import asyncio, asyncpg, os, re
url = os.environ['STAYWALLET_DATABASE_URL']
# asyncpg wants a plain postgres:// DSN (drop the +asyncpg driver suffix).
dsn = re.sub(r'\+asyncpg', '', url)
async def main():
    conn = await asyncpg.connect(dsn)
    await conn.close()
asyncio.run(main())
" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "[entrypoint] database not reachable after 30 tries — giving up." >&2
    exit 1
  fi
  sleep 2
done
echo "[entrypoint] database is up."

# ── Migrations ───────────────────────────────────────────────────────────
echo "[entrypoint] applying migrations (alembic upgrade head)…"
alembic upgrade head

# ── Demo seed (idempotent) ───────────────────────────────────────────────
echo "[entrypoint] seeding demo data…"
python -m app.db.seed

# ── Serve ────────────────────────────────────────────────────────────────
echo "[entrypoint] starting API on 0.0.0.0:8000…"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
