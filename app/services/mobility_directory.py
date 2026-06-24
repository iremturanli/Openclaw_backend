"""Mobility directory + integration roadmap (board/CEO vision).

Two pieces of structured, demoable data captured directly from the executive
brief:

1. :data:`COUNTRY_MOBILITY` -- the per-country ride-hailing / mobility provider
   map ("Türkiye: BiTaksi, Uber, Martı TAG; UAE: Careem, Uber; ..."). The app
   uses it to show the *correct local providers* for wherever the traveller is,
   instead of a single hard-coded Uber list.

2. :data:`ROADMAP_LAYERS` -- the 12-layer "AI travel finance super-app"
   integration roadmap (wallet/BaaS, card issuing, KYC/AML, travel booking,
   mobility, hotel key, loyalty, AI, etc.) with the recommended partner per
   capability and an honest live/sandbox/planned status.

Only Uber is wired today (deeplink hand-off + a sandbox Guest Trips adapter), so
its status is resolved from runtime settings; every other provider is flagged
``planned`` until its integration lands. Nothing here invents a live
integration that does not exist.
"""

from __future__ import annotations

from app.core.config import Settings

# Status vocabulary shared with the API models.
LIVE = "live"
SANDBOX = "sandbox"
PLANNED = "planned"


def _provider(
    name: str,
    *,
    kind: str = "ride-hailing",
    status: str = PLANNED,
    scheme: str | None = None,
    note: str | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "kind": kind,
        "status": status,
        "deeplinkScheme": scheme,
        "note": note,
    }


# ── 1. Country -> ranked mobility providers (executive brief, message 1) ──────
# Order matters: the first provider is the market leader / default suggestion.
# ``scheme`` enables a real deeplink hand-off where the app exposes one.
_COUNTRIES: list[dict[str, object]] = [
    {
        "code": "TR", "name": "Türkiye", "flag": "🇹🇷",
        "providers": [
            _provider("BiTaksi", kind="taxi", note="Türkiye taxi leader"),
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("Martı TAG", kind="scooter", note="Scooters + tag rides"),
        ],
    },
    {
        "code": "AE", "name": "United Arab Emirates", "flag": "🇦🇪",
        "providers": [
            _provider("Careem", note="Middle East leader"),
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
        ],
    },
    {
        "code": "US", "name": "United States", "flag": "🇺🇸",
        "providers": [
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("Lyft"),
        ],
    },
    {
        "code": "GB", "name": "United Kingdom", "flag": "🇬🇧",
        "providers": [
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("Bolt"),
            _provider("FREE NOW"),
        ],
    },
    {
        "code": "DE", "name": "Germany", "flag": "🇩🇪",
        "providers": [
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("FREE NOW"),
            _provider("Bolt"),
        ],
    },
    {
        "code": "FR", "name": "France", "flag": "🇫🇷",
        "providers": [
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("Bolt"),
            _provider("Heetch"),
        ],
    },
    {
        "code": "ES", "name": "Spain", "flag": "🇪🇸",
        "providers": [
            _provider("Cabify"),
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("Bolt"),
        ],
    },
    {
        "code": "IT", "name": "Italy", "flag": "🇮🇹",
        "providers": [
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("FREE NOW"),
        ],
    },
    {
        "code": "SA", "name": "Saudi Arabia", "flag": "🇸🇦",
        "providers": [
            _provider("Careem"),
            _provider("Jeeny"),
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
        ],
    },
    {
        "code": "QA", "name": "Qatar", "flag": "🇶🇦",
        "providers": [
            _provider("Karwa Taxi", kind="taxi"),
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("Careem"),
        ],
    },
    {
        "code": "EG", "name": "Egypt", "flag": "🇪🇬",
        "providers": [
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("Careem"),
            _provider("inDrive"),
        ],
    },
    {
        "code": "IN", "name": "India", "flag": "🇮🇳",
        "providers": [
            _provider("Ola"),
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("Rapido"),
        ],
    },
    {
        "code": "SG", "name": "Singapore", "flag": "🇸🇬",
        "providers": [
            _provider("Grab"),
            _provider("Gojek"),
            _provider("TADA"),
        ],
    },
    {
        "code": "ID", "name": "Indonesia", "flag": "🇮🇩",
        "providers": [
            _provider("Grab"),
            _provider("Gojek"),
        ],
    },
    {
        "code": "MY", "name": "Malaysia", "flag": "🇲🇾",
        "providers": [
            _provider("Grab"),
            _provider("AirAsia Ride"),
        ],
    },
    {
        "code": "TH", "name": "Thailand", "flag": "🇹🇭",
        "providers": [
            _provider("Grab"),
            _provider("Bolt"),
        ],
    },
    {
        "code": "JP", "name": "Japan", "flag": "🇯🇵",
        "providers": [
            _provider("GO Taxi", kind="taxi"),
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
        ],
    },
    {
        "code": "KR", "name": "South Korea", "flag": "🇰🇷",
        "providers": [
            _provider("Kakao T"),
            _provider("UT (Uber Taxi)", scheme="uber://"),
        ],
    },
    {
        "code": "CN", "name": "China", "flag": "🇨🇳",
        "providers": [
            _provider("DiDi"),
            _provider("T3 Mobility"),
        ],
    },
    {
        "code": "RU", "name": "Russia", "flag": "🇷🇺",
        "providers": [
            _provider("Yandex Go"),
            _provider("inDrive"),
        ],
    },
    {
        "code": "BR", "name": "Brazil", "flag": "🇧🇷",
        "providers": [
            _provider("99"),
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
        ],
    },
    {
        "code": "MX", "name": "Mexico", "flag": "🇲🇽",
        "providers": [
            _provider("Uber", scheme="uber://", note="Live app hand-off"),
            _provider("DiDi"),
            _provider("Cabify"),
        ],
    },
]

# Fallback when the traveller's country is not in the map: global leaders.
_DEFAULT_COUNTRY: dict[str, object] = {
    "code": "XX", "name": "Global", "flag": "🌍",
    "providers": [
        _provider("Uber", scheme="uber://", note="Live app hand-off"),
        _provider("Bolt"),
        _provider("FREE NOW"),
    ],
}


def country_mobility(country_code: str | None, settings: Settings) -> dict[str, object]:
    """Return the ranked mobility providers for ``country_code``.

    Uber's status reflects the real transfer-provider config; everything else
    is ``planned``. Unknown/empty country falls back to the global leaders.
    """

    code = (country_code or "").strip().upper()
    match = next((c for c in _COUNTRIES if c["code"] == code), None)
    chosen = match or _DEFAULT_COUNTRY
    uber_live = settings.transfer_provider == "uber"
    # Clone so we can stamp Uber's live status without mutating the table.
    providers: list[dict[str, object]] = []
    for prov in chosen["providers"]:  # type: ignore[union-attr]
        item = dict(prov)
        if str(item["name"]).startswith("Uber") or item["name"] == "UT (Uber Taxi)":
            item["status"] = SANDBOX if uber_live else PLANNED
            item["note"] = (
                "Guest Trips API (sandbox)" if uber_live else "Deeplink hand-off ready"
            )
        providers.append(item)
    return {
        "countryCode": chosen["code"],
        "countryName": chosen["name"],
        "flag": chosen["flag"],
        "providers": providers,
        "matched": match is not None,
    }


def all_countries() -> list[dict[str, object]]:
    """Every country in the directory (codes + names), for pickers."""

    return [
        {"code": c["code"], "name": c["name"], "flag": c["flag"]}
        for c in _COUNTRIES
    ]


# ── 2. Twelve-layer integration roadmap (executive brief, message 4) ──────────
def _layer(
    index: int,
    title: str,
    purpose: str,
    partners: list[tuple[str, str, str | None]],
) -> dict[str, object]:
    return {
        "index": index,
        "title": title,
        "purpose": purpose,
        "partners": [
            {"name": n, "status": s, "note": note} for (n, s, note) in partners
        ],
    }


# (name, status, capability-note). Status is honest: ``live`` only where the app
# truly calls the provider today; ``sandbox`` where a test integration exists;
# ``planned`` for partnership targets named in the brief.
ROADMAP_LAYERS: list[dict[str, object]] = [
    _layer(1, "Legal & Financial License", "Program-manager on licensed partners (don't apply for a bank licence first)", [
        ("EMI / BaaS partner (EU/UK/UAE/TR)", PLANNED, "Launch jurisdiction first"),
    ]),
    _layer(2, "Core Wallet / Banking", "Multi-currency wallet, IBANs, SEPA/SWIFT, FX, ledger", [
        ("OpenPayd", PLANNED, "Accounts + IBAN"),
        ("Banking Circle", PLANNED, "SEPA / cross-border"),
        ("Currencycloud", PLANNED, "FX conversion"),
        ("StayWallet ledger", SANDBOX, "Own demo wallet ledger"),
    ]),
    _layer(3, "Card Issuing", "Virtual + physical Visa/Mastercard travel cards", [
        ("Marqeta", PLANNED, "API-first issuer processor"),
        ("Paymentology", PLANNED, "Visa Ready certified"),
        ("Apple Pay / Google Pay", PLANNED, "Tokenization"),
    ]),
    _layer(4, "KYC / KYB / Compliance", "Identity, sanctions/PEP, monitoring, fraud", [
        ("Sumsub", PLANNED, "Identity verification"),
        ("ComplyAdvantage", PLANNED, "AML / sanctions"),
        ("Sardine", PLANNED, "Fraud + device intel"),
        ("On-device MRZ check-in", LIVE, "ML Kit passport scan"),
    ]),
    _layer(5, "Payments / Top-up / Checkout", "Card top-up, acquiring, travel checkout, refunds", [
        ("Stripe", SANDBOX, "Hosted Checkout (test mode) live"),
        ("Adyen", PLANNED, "Global acquiring target"),
        ("Checkout.com", PLANNED, "Alt acquirer"),
    ]),
    _layer(6, "Travel Booking", "Flights, hotels, cars, transfers, rail, activities, lounges, eSIM, insurance", [
        ("SerpApi (Google Flights/Hotels)", LIVE, "Live flight + hotel search"),
        ("Booking.com Demand", SANDBOX, "Cars adapter"),
        ("Amadeus / Duffel", PLANNED, "Flights GDS"),
        ("Hotelbeds", PLANNED, "Hotel content + booking"),
        ("Airalo", PLANNED, "eSIM"),
        ("Cover Genius", PLANNED, "Travel insurance"),
        ("DragonPass / Priority Pass", PLANNED, "Lounges"),
    ]),
    _layer(7, "Mobility / Ride-hailing", "Country-aware ride providers + airport transfers", [
        ("Uber", SANDBOX, "Guest Trips sandbox + deeplink"),
        ("Grab", PLANNED, "SE Asia (Phase 2)"),
        ("Careem", PLANNED, "Middle East (Phase 1)"),
        ("Bolt / FREE NOW / DiDi / Yandex Go", PLANNED, "Regional leaders"),
        ("Mozio / Jayride", PLANNED, "Airport-transfer aggregator"),
    ]),
    _layer(8, "Hotel Room Key / PMS", "Mobile key, PMS, check-in, guest messaging", [
        ("NFC mobile key", SANDBOX, "On-device NFC unlock demo"),
        ("Mews / Apaleo", PLANNED, "Modern PMS"),
        ("ASSA ABLOY / Salto", PLANNED, "Mobile key hardware"),
        ("Oracle Opera", PLANNED, "Large chains, later"),
    ]),
    _layer(9, "Loyalty / Rewards", "Cashback, card-linked offers, airline/hotel points", [
        ("StayWallet Points ledger", SANDBOX, "Own points engine"),
        ("Fidel API / Kard", PLANNED, "Card-linked offers"),
        ("Ascenda / Points.com", PLANNED, "Points marketplace"),
    ]),
    _layer(10, "AI Assistant", "Voice concierge, itinerary planning, booking automation", [
        ("OpenAI", LIVE, "Tool-calling agent, TR + EN"),
        ("ElevenLabs", LIVE, "Voice (TTS)"),
        ("DeepL", PLANNED, "Translation fallback"),
    ]),
    _layer(11, "Notifications / Comms", "Push, SMS OTP, email, WhatsApp, in-app chat", [
        ("Firebase / OneSignal", PLANNED, "Push"),
        ("Twilio / Vonage", PLANNED, "SMS OTP / WhatsApp"),
        ("SendGrid", PLANNED, "Email"),
    ]),
    _layer(12, "Security / Infrastructure", "Cloud, auth, secrets, analytics, crash, warehouse", [
        ("JWT auth (access/refresh)", LIVE, "Own auth service"),
        ("AWS / GCP", PLANNED, "Cloud target"),
        ("Sentry", PLANNED, "Crash reporting"),
        ("Mixpanel / Amplitude", PLANNED, "Analytics"),
    ]),
]


def integration_roadmap() -> dict[str, object]:
    """The full 12-layer roadmap with a rollup of live/sandbox/planned counts."""

    live = sandbox = planned = 0
    for layer in ROADMAP_LAYERS:
        for partner in layer["partners"]:  # type: ignore[union-attr]
            status = partner["status"]  # type: ignore[index]
            if status == LIVE:
                live += 1
            elif status == SANDBOX:
                sandbox += 1
            else:
                planned += 1
    return {
        "vision": (
            "StayWallet is an AI-powered travel finance super-app combining "
            "multi-currency banking, global mobility, hotel booking, card "
            "payments, loyalty, and an AI concierge in one platform."
        ),
        "phases": [
            {"name": "Phase 1", "detail": "Uber + Grab + Careem mobility; Stripe + flights/hotels live"},
            {"name": "Phase 2", "detail": "Gojek, Kakao T, GO Taxi, Yandex Go; card issuing + KYC"},
            {"name": "Phase 3", "detail": "Transport aggregator (Distribusion/Amadeus); BaaS + IBAN"},
        ],
        "liveCount": live,
        "sandboxCount": sandbox,
        "plannedCount": planned,
        "layers": ROADMAP_LAYERS,
    }
