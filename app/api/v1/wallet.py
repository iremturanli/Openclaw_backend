"""Smart FX / multi-currency wallet (authenticated).

Shows the traveller's wallet value across many world currencies at LIVE ECB
rates, plus a smart-conversion preview. Be HONEST: the FX rates are real (ECB,
via frankfurter.dev); the multi-currency *pockets* are a demo split of the one
real travel balance and never move real money (flagged ``isDemo``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user, get_wallet_service
from app.db.models.user import UserORM
from app.models.wallet_currency import (
    AvailableCurrency,
    ConvertOut,
    ConvertRequest,
    CurrencyHolding,
    WalletCurrenciesOut,
)
from app.services import fx_service
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/wallet", tags=["wallet"])

# Currency catalogue: ISO code -> (display name, flag emoji). ~45 major world
# currencies — the board says "180+"; this honest subset covers the big ones.
_CURRENCIES: dict[str, tuple[str, str]] = {
    "USD": ("US Dollar", "🇺🇸"),
    "EUR": ("Euro", "🇪🇺"),
    "GBP": ("British Pound", "🇬🇧"),
    "JPY": ("Japanese Yen", "🇯🇵"),
    "CHF": ("Swiss Franc", "🇨🇭"),
    "CAD": ("Canadian Dollar", "🇨🇦"),
    "AUD": ("Australian Dollar", "🇦🇺"),
    "NZD": ("New Zealand Dollar", "🇳🇿"),
    "CNY": ("Chinese Yuan", "🇨🇳"),
    "HKD": ("Hong Kong Dollar", "🇭🇰"),
    "SGD": ("Singapore Dollar", "🇸🇬"),
    "INR": ("Indian Rupee", "🇮🇳"),
    "TRY": ("Turkish Lira", "🇹🇷"),
    "AED": ("UAE Dirham", "🇦🇪"),
    "SAR": ("Saudi Riyal", "🇸🇦"),
    "QAR": ("Qatari Riyal", "🇶🇦"),
    "KWD": ("Kuwaiti Dinar", "🇰🇼"),
    "ZAR": ("South African Rand", "🇿🇦"),
    "MXN": ("Mexican Peso", "🇲🇽"),
    "BRL": ("Brazilian Real", "🇧🇷"),
    "ARS": ("Argentine Peso", "🇦🇷"),
    "CLP": ("Chilean Peso", "🇨🇱"),
    "COP": ("Colombian Peso", "🇨🇴"),
    "SEK": ("Swedish Krona", "🇸🇪"),
    "NOK": ("Norwegian Krone", "🇳🇴"),
    "DKK": ("Danish Krone", "🇩🇰"),
    "PLN": ("Polish Zloty", "🇵🇱"),
    "CZK": ("Czech Koruna", "🇨🇿"),
    "HUF": ("Hungarian Forint", "🇭🇺"),
    "RON": ("Romanian Leu", "🇷🇴"),
    "BGN": ("Bulgarian Lev", "🇧🇬"),
    "ISK": ("Icelandic Krona", "🇮🇸"),
    "RUB": ("Russian Ruble", "🇷🇺"),
    "UAH": ("Ukrainian Hryvnia", "🇺🇦"),
    "ILS": ("Israeli Shekel", "🇮🇱"),
    "EGP": ("Egyptian Pound", "🇪🇬"),
    "MAD": ("Moroccan Dirham", "🇲🇦"),
    "NGN": ("Nigerian Naira", "🇳🇬"),
    "KES": ("Kenyan Shilling", "🇰🇪"),
    "THB": ("Thai Baht", "🇹🇭"),
    "MYR": ("Malaysian Ringgit", "🇲🇾"),
    "IDR": ("Indonesian Rupiah", "🇮🇩"),
    "PHP": ("Philippine Peso", "🇵🇭"),
    "VND": ("Vietnamese Dong", "🇻🇳"),
    "KRW": ("South Korean Won", "🇰🇷"),
    "TWD": ("New Taiwan Dollar", "🇹🇼"),
}

# Demo pockets: secondary display currencies and the fraction of a notional
# amount allocated to each (deterministic, no real-money meaning). The remainder
# stays in the real wallet currency as the primary pocket.
_DEMO_POCKETS: list[tuple[str, float]] = [
    ("EUR", 0.18),
    ("GBP", 0.10),
    ("TRY", 0.06),
    ("AED", 0.06),
    ("JPY", 0.10),
]

_LIVE_NOTE = (
    "Live ECB rates; multi-currency pockets are a demo split of your travel "
    "balance."
)
_FALLBACK_NOTE = (
    "FX provider unreachable — using fallback rates; multi-currency pockets are "
    "a demo split of your travel balance."
)


def _currency_meta(code: str) -> tuple[str, str]:
    """Return (name, flag) for an ISO code, with a neutral default."""

    return _CURRENCIES.get(code, (code, "🏳️"))


@router.get(
    "/currencies",
    response_model=WalletCurrenciesOut,
    summary="Multi-currency wallet value at live FX rates",
)
async def get_currencies(
    user: UserORM = Depends(get_current_user),
    wallet: WalletService = Depends(get_wallet_service),
) -> WalletCurrenciesOut:
    """Value the traveller's wallet across major currencies at live ECB rates.

    The real single balance is the ``primary`` pocket in the wallet currency;
    additional demo pockets are split deterministically from a notional amount
    in other major currencies. The real budget is never touched.
    """

    budget = await wallet.ensure_budget(user.guest_id)
    base = budget.currency.upper()
    real_balance = budget.balance_cents

    fx = await fx_service.get_rates(base)

    # Primary pocket = the real wallet balance, by definition rate 1.0.
    primary_name, primary_flag = _currency_meta(base)
    holdings: list[CurrencyHolding] = [
        CurrencyHolding(
            currency=base,
            name=primary_name,
            flag=primary_flag,
            balance_cents=real_balance,
            value_base_cents=real_balance,
            rate=1.0,
            primary=True,
        )
    ]

    # Demo pockets: split a notional amount equal to the real balance so the
    # numbers feel proportional, without ever mutating the real budget.
    for code, fraction in _DEMO_POCKETS:
        if code == base:
            continue
        rate = fx.rate(code)
        if rate is None:
            continue
        # value_base_cents allocated to this pocket, then expressed in its own
        # currency at the live rate.
        value_base = round(real_balance * fraction)
        pocket_balance = round(value_base * rate)
        name, flag = _currency_meta(code)
        holdings.append(
            CurrencyHolding(
                currency=code,
                name=name,
                flag=flag,
                balance_cents=pocket_balance,
                value_base_cents=value_base,
                rate=round(rate, 6),
                primary=False,
            )
        )

    total_value = sum(h.value_base_cents for h in holdings)

    available = [
        AvailableCurrency(code=code, name=name, flag=flag)
        for code, (name, flag) in _CURRENCIES.items()
    ]

    return WalletCurrenciesOut(
        base_currency=base,
        total_value_base_cents=total_value,
        holdings=holdings,
        available_currencies=available,
        is_demo=True,
        note=_LIVE_NOTE if fx.live else _FALLBACK_NOTE,
    )


@router.post(
    "/convert",
    response_model=ConvertOut,
    summary="Smart-conversion preview at live FX rates (no money moves)",
)
async def convert(
    request: ConvertRequest,
    user: UserORM = Depends(get_current_user),
) -> ConvertOut:
    """Preview converting ``amountCents`` from one currency to another.

    Uses live ECB rates; performs NO real money movement and does not mutate any
    wallet balance. ``rate`` is units of ``toCurrency`` per 1 ``fromCurrency``.
    """

    src = request.from_currency.upper()
    dst = request.to_currency.upper()

    if src == dst:
        return ConvertOut(
            from_currency=src,
            to_currency=dst,
            from_amount_cents=request.amount_cents,
            to_amount_cents=request.amount_cents,
            rate=1.0,
            fee_pct=0.0,
            is_demo=True,
        )

    fx = await fx_service.get_rates(src)
    rate = fx.rate(dst)
    if rate is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported currency pair {src}->{dst}.",
        )

    to_amount = round(request.amount_cents * rate)
    return ConvertOut(
        from_currency=src,
        to_currency=dst,
        from_amount_cents=request.amount_cents,
        to_amount_cents=to_amount,
        rate=round(rate, 6),
        fee_pct=0.0,
        is_demo=True,
    )
