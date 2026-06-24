"""Live FX rates (ECB reference data via the free frankfurter.dev API).

This centralises the rate-fetch logic that used to live inline in the PaxPal
``/fx`` endpoint so multiple features (PaxPal, the multi-currency wallet) share
one cache and one honest fallback. Rates are real ECB data; when the provider is
unreachable a small deterministic table is returned so dependent features can
still answer (callers should flag the result as a fallback / demo).
"""

from __future__ import annotations

import time

import httpx

# Module-level cache shared across requests: base -> (monotonic_ts, rates).
_FX_CACHE: dict[str, tuple[float, dict[str, float]]] = {}
_FX_TTL_SECONDS = 3600.0
_PROVIDER_URL = "https://api.frankfurter.dev/v1/latest"

# Deterministic fallback rates (units per 1 USD) used only when the live
# provider is unreachable. Approximate, clearly NOT live — callers flag this.
_FALLBACK_USD_RATES: dict[str, float] = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "TRY": 32.0,
    "AED": 3.67,
    "JPY": 157.0,
    "CHF": 0.89,
    "CAD": 1.36,
    "AUD": 1.51,
    "CNY": 7.24,
    "INR": 83.3,
    "SGD": 1.35,
}


class FxResult:
    """Outcome of an FX fetch: the base, the rate map and whether it is live."""

    def __init__(self, base: str, rates: dict[str, float], *, live: bool) -> None:
        self.base = base
        self.rates = rates
        self.live = live

    def rate(self, currency: str) -> float | None:
        """Return units of ``currency`` per 1 ``base``, or ``None`` if unknown."""

        if currency == self.base:
            return 1.0
        return self.rates.get(currency)


def _fallback_for_base(base: str) -> FxResult:
    """Derive a fallback rate map for any base from the USD-anchored table."""

    base_per_usd = _FALLBACK_USD_RATES.get(base)
    if not base_per_usd:
        # Unknown base: anchor to USD itself.
        return FxResult("USD", dict(_FALLBACK_USD_RATES), live=False)
    rates = {
        code: round(units / base_per_usd, 6)
        for code, units in _FALLBACK_USD_RATES.items()
    }
    return FxResult(base, rates, live=False)


async def get_rates(base: str = "USD") -> FxResult:
    """Fetch live ECB rates for ``base`` (cached 1h); fall back deterministically.

    Returns a :class:`FxResult` whose ``rates`` maps ISO currency code to units
    of that currency per 1 unit of ``base``. ``live`` is ``True`` for real ECB
    data and ``False`` when the deterministic fallback table was used.
    """

    base = base.upper()
    cached = _FX_CACHE.get(base)
    if cached and time.monotonic() - cached[0] < _FX_TTL_SECONDS:
        return FxResult(base, dict(cached[1]), live=True)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(_PROVIDER_URL, params={"base": base})
        if resp.status_code != 200:
            return _fallback_for_base(base)
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return _fallback_for_base(base)

    rates = {k: float(v) for k, v in (data.get("rates") or {}).items()}
    if not rates:
        return _fallback_for_base(base)
    resolved_base = str(data.get("base", base)).upper()
    _FX_CACHE[resolved_base] = (time.monotonic(), rates)
    return FxResult(resolved_base, rates, live=True)
