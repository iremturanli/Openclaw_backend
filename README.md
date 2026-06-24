# StayWallet — Backend (FastAPI + PostgreSQL)

Passport-based hotel self check-in, in-stay room service, AI-concierge voice
proxy, and **Travel Services + Loyalty** API consumed by the StayWallet Flutter
app. Implements the contract in [`../docs/api_contract.md`](../docs/api_contract.md)
exactly (base path `/api/v1`, camelCase JSON keys, ISO-8601 UTC `Z` timestamps,
money in integer cents).

Persistence is **real PostgreSQL** via SQLAlchemy 2.0 async (asyncpg). Schema is
owned by **Alembic migrations** (no `create_all` at app startup). The loyalty
balance is a **real ledger sum**, never a hardcoded number.

## Project layout

```
backend/
├── app/
│   ├── main.py                 # FastAPI app, CORS, router includes, /health
│   ├── core/config.py          # pydantic-settings (DB URLs, loyalty rule, ...)
│   ├── db/
│   │   ├── base.py             # DeclarativeBase (Base)
│   │   ├── session.py          # async engine + sessionmaker + get_session dep
│   │   ├── seed.py             # idempotent demo seed (python -m app.db.seed)
│   │   └── models/             # ORM models (stays, orders, travel, loyalty, ...)
│   ├── api/
│   │   ├── deps.py             # DB-backed repo/service wiring (per request)
│   │   └── v1/                 # stays, check_ins, orders, voice, travel, loyalty
│   ├── models/                 # Pydantic API schemas (request/response shapes)
│   ├── services/               # business logic (check_in, order, loyalty, travel,
│   │   │                       #   connection) + connectors/ (provider framework)
│   │   └── connectors/         # ProviderConnector ABC, registry, BookingCom (sandbox)
│   └── repositories/           # Protocol interfaces + DB-backed implementations
├── alembic/                    # migration env + versions/ (initial schema)
├── alembic.ini
├── tests/                      # pytest-asyncio + httpx against a real test DB
├── docker-compose.yml          # Postgres 16 (host port 5544)
├── requirements.txt
└── README.md
```

The repository layer is defined as async `Protocol` interfaces
(`app/repositories/base.py`) with DB-backed implementations
(`app/repositories/db.py`). Services depend only on the Protocols, so
persistence can change without touching business logic. **No business logic
lives in routers** — they only translate domain exceptions to HTTP responses.

## Running locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # if not already created
pip install -r requirements.txt

# 1. Start Postgres (host port 5544; user/pass/db all "staywallet").
docker compose up -d db          # or: docker-compose up -d db

# 2. Build the schema from migrations (authoritative source of truth).
alembic upgrade head

# 3. Seed demo data (idempotent): demo guest, stays, menu, travel catalogue,
#    and a loyalty ledger summing to 12450 points for guest_demo.
python -m app.db.seed

# 4. Run the API.
uvicorn app.main:app --reload --port 8000
```

Interactive docs: <http://127.0.0.1:8000/docs> · Health: <http://127.0.0.1:8000/health>

> **Note:** if `docker compose` (plugin form) is unavailable, the standalone
> `docker-compose` binary works identically.

## Database configuration

Settings are read from environment variables prefixed `STAYWALLET_` (see
`app/core/config.py`); `.env` is gitignored. No secrets are committed.

| Variable                       | Purpose                                  |
|--------------------------------|------------------------------------------|
| `STAYWALLET_DATABASE_URL`      | Async (asyncpg) URL used by the app      |
| `STAYWALLET_DATABASE_URL_SYNC` | Sync (psycopg2) URL used by Alembic      |

Defaults point at the docker-compose `db` service on `localhost:5544`. To point
at **managed Postgres**, override both, e.g.:

```bash
export STAYWALLET_DATABASE_URL="postgresql+asyncpg://USER:PASS@HOST:5432/DB"
export STAYWALLET_DATABASE_URL_SYNC="postgresql+psycopg2://USER:PASS@HOST:5432/DB"
alembic upgrade head && uvicorn app.main:app
```

Alembic reads the **sync** URL from settings at runtime (see `alembic/env.py`),
so migrations work without an event loop and no URL is stored in `alembic.ini`.

## Migrations

```bash
alembic upgrade head                       # apply all migrations
alembic revision --autogenerate -m "..."   # create a new migration from models
alembic downgrade -1                        # roll back one
```

The initial migration under `alembic/versions/` builds the full schema:
`guests`, `stays`, `check_ins`, `digital_keys`, `menu_items`, `orders`,
`order_lines`, `travel_categories`, `featured_deals`, `bookings`, and the
`loyalty_transactions` ledger.

## Loyalty earn rule

The loyalty balance is computed as `SUM(amount)` over a guest's
`loyalty_transactions` rows (earn rows positive, redeem rows negative) — there
is no stored balance column. Both **room-service orders** and **travel bookings**
write an **earn** row through the single `LoyaltyService`, atomically within the
same request transaction as the order/booking (if the commit fails, no points
are awarded).

```
points = floor(total_cents / 100) * points_per_dollar * multiplier
```

* `points_per_dollar` defaults to **1** (1 point per whole dollar).
* Room service uses a **1x** multiplier (e.g. a $23.80 order → 23 points).
* Travel bookings use the **3x** travel multiplier to match the "3x points"
  promo (e.g. a $150 rental car → 150 × 3 = 450 points).

All multipliers/labels are configurable via `STAYWALLET_LOYALTY_*` settings.
Room-service orders accrue to the demo member `guest_demo`
(`STAYWALLET_DEMO_GUEST_ID`) since orders carry no guest id in the contract.

## Endpoints

| Method | Path                                   | Description                                   |
|--------|----------------------------------------|-----------------------------------------------|
| GET    | `/health`                              | Liveness probe                                |
| GET    | `/api/v1/stays/{stayId}`               | Fetch a booking (`StayInfo`); 404 if unknown  |
| POST   | `/api/v1/check-ins`                    | Submit check-in (multipart); issues a key     |
| GET    | `/api/v1/check-ins/{id}`               | Fetch a check-in / wallet state               |
| GET    | `/api/v1/stays/{stayId}/menu`          | Room-service menu                             |
| POST   | `/api/v1/stays/{stayId}/orders`        | Place an order (earns loyalty points)         |
| GET    | `/api/v1/stays/{stayId}/orders`        | List a stay's orders (most recent first)      |
| POST   | `/api/v1/voice/tts`                     | AI-concierge TTS proxy (ElevenLabs)           |
| GET    | `/api/v1/travel/categories`            | `ServiceCategory[]`                           |
| GET    | `/api/v1/travel/deals`                 | `FeaturedDeal[]`                              |
| GET    | `/api/v1/loyalty?guestId=...`          | `LoyaltyBalance` (from the ledger)            |
| POST   | `/api/v1/travel/bookings`              | Book a service; earns points; 404/422 cases   |
| POST   | `/api/v1/connections/booking/link`     | Link Booking.com (sandbox); imports stays     |
| GET    | `/api/v1/connections?guestId=...`      | `ProviderConnection[]` for a guest            |
| DELETE | `/api/v1/connections/{connectionId}`   | Unlink (204); imported stays are kept         |
| GET    | `/api/v1/orchestrator?guestId=...`     | `OrchestratorSummary` (cross-ecosystem points)|
| POST   | `/api/v1/orchestrator/link`            | Link one discovered ecosystem; 404/409 cases  |
| POST   | `/api/v1/orchestrator/auto-scan`       | Link every discovered ecosystem; re-aggregate |

Seeded demo data: guest `guest_demo` (12450 points), stays `stay_123` /
`stay_456`, menu (`m_burger`, `m_cola`, ...), travel categories
(`rental_car`, `hotel`, `restaurants`, `travel_insurance`, `e_visa`), the
`porsche_911` featured deal, and the Loyalty Orchestrator catalog + accounts
(see below).

## Provider connections (connector framework)

A provider-agnostic **connector framework** links a guest's external travel
account and syncs its data into real rows. The pieces:

- **`app/services/connectors/base.py`** — `ProviderConnector` ABC with an
  OAuth-shaped contract: `authorize_url(state)` → `exchange_code(code) -> token`
  → `fetch_profile(token)` → `fetch_bookings(token)`. Connectors return plain
  dataclasses; they never touch the database.
- **`app/services/connectors/registry.py`** — maps `provider` → connector
  (e.g. `"booking.com"`). Adding Airbnb/Expedia later is a one-liner
  `register_connector(...)`; nothing else changes.
- **`app/services/connection_service.py`** — provider-agnostic orchestration:
  validate guest → resolve connector → authorize/exchange → create the
  `provider_connections` row → if `sync_genius` store `geniusLevel`, if
  `import_bookings` import reservations as `stays`, if `expense_tracking` record
  the scope. All of this runs inside the request's unit of work, so the
  connection, imported stays and Genius level **commit or roll back together**.

### Honest sandbox note

> **Booking.com has no public consumer API** to read a traveler's Genius level
> or reservations. So **`BookingComConnector` runs in sandbox mode**: it returns
> deterministic, clearly-labelled simulated data (Genius level 2, two upcoming
> reservations) and every connection it produces is flagged `sandbox: true`. The
> OAuth shape and every row written to Postgres are **real**; only the external
> data is stubbed, and the stub is isolated to that single connector file.

### Swapping in a real partnership

Obtain Booking.com partner/affiliate (or Connectivity) credentials, then replace
**only** the bodies of `exchange_code` / `fetch_profile` / `fetch_bookings` in
`app/services/connectors/booking.py` with real HTTP calls and point
`authorize_url` at the real consent screen + callback. Flip `sandbox=False` on
the returned token. The service, repository, router, schema and DB are unchanged.

### Imported stays

Imported reservations are stored as `stays` rows tagged `source='booking.com'`,
linked via `provider_connection_id`, and keyed by a deterministic unique
`external_ref` so **re-linking never duplicates** them. On **unlink** the
connection row is deleted but its imported stays are **kept** — the FK's
`ON DELETE SET NULL` nulls `provider_connection_id`, so the traveler keeps the
imported itinerary.

## Loyalty Orchestrator (cross-ecosystem aggregator)

The orchestrator aggregates a guest's loyalty points across every linked
ecosystem and surfaces "discovered" programs they could link. It is backed by
two tables:

- **`providers`** — the catalog of loyalty ecosystems StayWallet knows about
  (reference data: `id` slug, `name`, `brand_color_hex`, `logo_url`, `icon`,
  `category`, `sort_order`). No per-guest state.
- **`loyalty_accounts`** — a guest's relationship to one catalog provider. A row
  is either **linked** (`linked=true`, `points` set — counts toward the
  aggregate) or **discovered** (`discovered=true`, `detected_label` set —
  surfaced as "you could link this"). A unique `(guest_id, provider_id)`
  constraint keeps the relationship 1:1, so linking just **flips the flags** on
  the existing row rather than inserting a duplicate.

### Schema choice

A dedicated `loyalty_accounts` table (rather than reusing `provider_connections`)
keeps two distinct concerns separate: `provider_connections` models an
OAuth-style *connection* (scopes, Genius level, imported stays), while a loyalty
account models *membership points in an ecosystem*. The unique
`(guest_id, provider_id)` pair makes `link` an atomic flag flip with no risk of
duplicates, and the aggregate is always `SUM(points WHERE linked)` — never a
stored running total. Linking **also** writes a real, `sandbox=true`
`provider_connections` row (provider `orchestrator:<id>`) through the connector
framework, so every orchestrator link is auditable like any other connection.

### Aggregation rules

- `totalPoints`     = `SUM(points)` over the guest's **linked** accounts.
- `ecosystemsCount` = number of linked accounts.
- `ecosystemsNew`   = linked accounts created within the trailing
  `orchestrator_new_window_days` window (default 30 days; seed = 2).
- `trendPct`        = `orchestrator_trend_pct` setting (default/seed = 12).
- `integrations`    = linked accounts (points set), brand-ordered by `sort_order`
  so `booking_com`, `sixt`, `miles_smiles` lead the grid.
- `discovered`      = discovered-but-not-linked accounts (`detectedLabel` set,
  `points` hidden until linked).

`POST /orchestrator/link` returns **404** for an unknown guest/provider and
**409 Conflict** if the provider is already linked. `auto-scan` links every
currently-discovered ecosystem in one transaction.

### Seed math (how the demo reaches 1,240,500)

The demo guest is seeded with **12 linked** ecosystems whose points sum to
exactly **1,240,500**: `booking_com` 845,000 + `sixt` 8,200 +
`miles_smiles` 120,300 + `hilton_honors` 64,000 + `ihg_one` 42,000 +
`emirates_skywards` 78,500 + `avis` 15,600 + `shell_go` 9,400 +
`starbucks` 3,100 + `turkish_airlines_extra` 21,500 + `world_of_hyatt` 18,900 +
`accor_all` 14,000. Two of them (`sixt`, `miles_smiles`) carry a recent
`created_at` so `ecosystemsNew == 2`. Three ecosystems are left **discovered**:
`uber` ("2,450 points detected"), `amex` ("Elite access found") and `marriott`
("Titanium Elite detected"); their seeded membership points (2,450 / 31,000 /
56,000) fold into the total when linked.

### Honest sandbox note

> Most of these programs (Sixt, Uber, Amex, Marriott, …) have **no public
> consumer API** to read a member's balance. Discovered providers are therefore
> **simulated (sandbox)**: their points/labels are seeded sandbox data, and every
> connection a link produces is flagged `sandbox: true`. The catalog, the
> per-guest accounts and every row written to Postgres are **real**; only the
> external membership data is stubbed. Going live for one program means
> registering a real connector under its provider id — nothing else changes
> (`app/services/connectors/sandbox.py`).

## Tests

Tests run against a **real, dedicated Postgres test database** (`staywallet_test`
on the same server). The DB is created once per session, the schema is built
from ORM metadata, and every test starts from a clean, freshly-seeded state
(TRUNCATE + reseed) for isolation. No mocks, no in-memory fakes.

```bash
docker compose up -d db          # the test DB is created on the same server
.venv/bin/python -m pytest -q
```

## Validation & error decisions

- **Unknown stay** → `404` `{ "detail": "Stay not found" }`.
- **Unknown menu item** → `404` `{ "detail": "Menu item not found" }`.
- **Unknown travel category/deal** → `404` `{ "detail": "Travel category or deal not found" }`.
- **Unknown guest (booking/connection)** → `404` `{ "detail": "Guest not found" }`.
- **Booking with neither `categoryId` nor `dealId`** → `422` (Pydantic).
- **Unknown provider on link** → `404` `{ "detail": "Unknown provider" }`.
- **Unknown connection on unlink** → `404` `{ "detail": "Connection not found" }`.
- **Link with empty `scopes`** → `422` (Pydantic `min_length=1`).
- **Structural payload errors** (missing fields, wrong types, malformed JSON) → `422`.
- **Expired passport / bad MRZ checksum** → check-in is *accepted and persisted*
  with `status: "rejected"`, a reason, and **no `digitalKey`** (so the wallet can
  render the rejected state rather than a generic validation failure).

## Digital key

On a verified check-in, `key_service` issues an opaque, JWT-like token: a
base64url claims payload (`kid`, `sid`, `room`, `nbf`, `exp`, random `jti`) plus
an HMAC-SHA256 signature. `validFrom` / `validUntil` are bound to the stay's
check-in / check-out dates. The signing secret is configurable via
`STAYWALLET_KEY_SIGNING_SECRET` (the default is a demo placeholder — override in
production).
