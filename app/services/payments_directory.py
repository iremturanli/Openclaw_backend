"""Payment-provider auto-switch directory (board/CEO vision).

A small, demoable *recommendation* layer: given the traveller's country (and
optionally currency), pick the BEST card network to use there for highest
acceptance + lowest fees, plus a best-first ranked list of every other known
network with an ``available`` flag and an optional note where acceptance is
limited.

This is an HONEST intelligence layer -- it does NOT move money. Actual
settlement still runs through the existing Stripe sandbox. Every acceptance /
fee figure here is illustrative demo data and the response is flagged
``isDemo: true``.

Mirrors :mod:`app.services.mobility_directory`: a ``_network(...)`` helper, a
per-country curated table, a default fallback, and a resolver
(:func:`recommend_provider`). Stdlib + :class:`Settings` only -- importing this
module never pulls in ``openai`` or any network client.
"""

from __future__ import annotations

from app.core.config import Settings

# ── Canonical network catalogue (display names from the brief) ────────────────
# id -> human display name. ``troy`` is intentionally lowercase (brand style).
_NETWORK_NAMES: dict[str, str] = {
    "visa": "Visa",
    "mastercard": "Mastercard",
    "amex": "Amex",
    "unionpay": "UnionPay",
    "mir": "МИР",
    "troy": "troy",
}


def _network(
    network_id: str,
    *,
    acceptance_pct: int,
    fee_pct: float,
    available: bool = True,
    note: str | None = None,
) -> dict[str, object]:
    """Build one network entry for a country's routing table.

    ``acceptance_pct`` / ``fee_pct`` are illustrative demo figures. When
    ``available`` is False the network is shown but flagged unusable, usually
    with a neutral ``note`` (e.g. "Limited acceptance here").
    """

    return {
        "id": network_id,
        "name": _NETWORK_NAMES[network_id],
        "network": network_id,
        "acceptancePct": acceptance_pct,
        "feePct": fee_pct,
        "available": available,
        "note": note,
    }


# ── Per-country routing tables (illustrative demo data) ───────────────────────
# Each entry: country meta + the recommended network id + the full network set.
# The recommended network is curated to be internally consistent -- it has the
# highest acceptance and lowest fee of the available networks for that country.
_COUNTRIES: list[dict[str, object]] = [
    {
        "code": "TR", "name": "Türkiye", "flag": "🇹🇷",
        "recommended": "troy",
        "reason": "Domestic Turkish network — highest acceptance and lowest fees here",
        "networks": [
            _network("troy", acceptance_pct=98, fee_pct=0.6),
            _network("visa", acceptance_pct=95, fee_pct=1.8),
            _network("mastercard", acceptance_pct=94, fee_pct=1.9),
            _network("amex", acceptance_pct=78, fee_pct=2.8),
            _network("unionpay", acceptance_pct=60, fee_pct=2.2),
            _network("mir", acceptance_pct=0, fee_pct=0.0, available=False,
                     note="Limited acceptance here"),
        ],
    },
    {
        "code": "RU", "name": "Russia", "flag": "🇷🇺",
        "recommended": "mir",
        "reason": "Domestic Russian network — highest acceptance and lowest fees here",
        "networks": [
            _network("mir", acceptance_pct=98, fee_pct=0.5),
            _network("unionpay", acceptance_pct=82, fee_pct=1.6),
            _network("visa", acceptance_pct=0, fee_pct=0.0, available=False,
                     note="Limited acceptance here"),
            _network("mastercard", acceptance_pct=0, fee_pct=0.0, available=False,
                     note="Limited acceptance here"),
            _network("amex", acceptance_pct=0, fee_pct=0.0, available=False,
                     note="Not accepted here"),
            _network("troy", acceptance_pct=0, fee_pct=0.0, available=False,
                     note="Limited acceptance here"),
        ],
    },
    {
        "code": "CN", "name": "China", "flag": "🇨🇳",
        "recommended": "unionpay",
        "reason": "Domestic Chinese network — highest acceptance and lowest fees here",
        "networks": [
            _network("unionpay", acceptance_pct=99, fee_pct=0.5),
            _network("visa", acceptance_pct=70, fee_pct=2.0),
            _network("mastercard", acceptance_pct=68, fee_pct=2.1),
            _network("amex", acceptance_pct=45, fee_pct=2.9, available=False,
                     note="Limited acceptance here"),
            _network("troy", acceptance_pct=0, fee_pct=0.0, available=False,
                     note="Limited acceptance here"),
            _network("mir", acceptance_pct=0, fee_pct=0.0, available=False,
                     note="Limited acceptance here"),
        ],
    },
]

# Global set for the "most others" markets (AE/US/GB/DE/FR…) and the fallback.
# Visa leads on global acceptance; Mastercard a close second.
_GLOBAL_NETWORKS: list[dict[str, object]] = [
    _network("visa", acceptance_pct=99, fee_pct=1.5),
    _network("mastercard", acceptance_pct=98, fee_pct=1.6),
    _network("amex", acceptance_pct=85, fee_pct=2.6),
    _network("unionpay", acceptance_pct=70, fee_pct=2.0),
    _network("mir", acceptance_pct=0, fee_pct=0.0, available=False,
             note="Limited acceptance here"),
    _network("troy", acceptance_pct=0, fee_pct=0.0, available=False,
             note="Limited acceptance here"),
]


def _global_country(code: str, name: str, flag: str) -> dict[str, object]:
    """A Visa-led market that uses the shared global network set."""

    return {
        "code": code, "name": name, "flag": flag,
        "recommended": "visa",
        "reason": "Highest global acceptance — works almost everywhere here",
        "networks": _GLOBAL_NETWORKS,
    }


# Visa-recommended markets named in the brief ("AE, US, GB, DE, FR and most
# others"). They share the global network set rather than duplicating tables.
_COUNTRIES.extend([
    _global_country("AE", "United Arab Emirates", "🇦🇪"),
    _global_country("US", "United States", "🇺🇸"),
    _global_country("GB", "United Kingdom", "🇬🇧"),
    _global_country("DE", "Germany", "🇩🇪"),
    _global_country("FR", "France", "🇫🇷"),
])

# Fallback when the traveller's country is unknown: global Visa-led set.
_DEFAULT_COUNTRY: dict[str, object] = _global_country("XX", "Global", "🌍")


def _rank_key(net: dict[str, object]) -> tuple[int, int, float]:
    """Sort key for best-first ranking: available first, then acceptance desc,
    then fee asc."""

    return (
        0 if net["available"] else 1,
        -int(net["acceptancePct"]),  # type: ignore[arg-type]
        float(net["feePct"]),  # type: ignore[arg-type]
    )


def recommend_provider(
    country_code: str | None,
    currency: str | None,
    settings: Settings,
) -> dict[str, object]:
    """Recommend the best card network for ``country_code``.

    Returns the single best ``recommended`` network plus best-first ranked
    ``alternatives`` (every OTHER known network, each with ``available`` and an
    optional ``note``). Unknown/empty country falls back to the global Visa-led
    set. ``currency`` is accepted for the shared contract and echoed back; it
    does not currently change the recommendation. ``settings`` is accepted to
    mirror :func:`mobility_directory.country_mobility` (e.g. for a future
    settings-driven default) -- ``demo_budget_currency`` seeds the echoed
    currency when none is supplied.

    The response is honest demo data: ``isDemo`` is True and the ``note`` makes
    clear that real settlement still runs through the Stripe sandbox.
    """

    code = (country_code or "").strip().upper()
    match = next((c for c in _COUNTRIES if c["code"] == code), None)
    chosen = match or _DEFAULT_COUNTRY

    networks: list[dict[str, object]] = list(chosen["networks"])  # type: ignore[arg-type]
    recommended_id = chosen["recommended"]
    rec = next(n for n in networks if n["id"] == recommended_id)

    recommended = {
        "id": rec["id"],
        "name": rec["name"],
        "network": rec["network"],
        "acceptancePct": rec["acceptancePct"],
        "feePct": rec["feePct"],
        "reason": chosen["reason"],
        "badge": "BEST FOR YOU",
    }

    alternatives = [
        {
            "id": n["id"],
            "name": n["name"],
            "network": n["network"],
            "acceptancePct": n["acceptancePct"],
            "feePct": n["feePct"],
            "available": n["available"],
            "note": n["note"],
        }
        for n in sorted(networks, key=_rank_key)
        if n["id"] != recommended_id
    ]

    echoed_currency = (currency or "").strip().upper() or None

    return {
        "country": chosen["code"],
        "countryName": chosen["name"],
        "flag": chosen["flag"],
        "currency": echoed_currency or settings.demo_budget_currency,
        "matched": match is not None,
        "recommended": recommended,
        "alternatives": alternatives,
        "isDemo": True,
        "note": (
            "Smart-routing recommendation. Actual settlement runs through the "
            "Stripe sandbox."
        ),
    }
