"""Wire schemas for the Smart FX / multi-currency wallet.

Live ECB rates are real; the multi-pocket holdings are an honest demo split of
the traveller's single real travel balance (flagged ``isDemo``). No real money
moves through these endpoints.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CurrencyHolding(BaseModel):
    """One currency pocket in the wallet, valued at live rates against the base."""

    currency: str
    name: str
    flag: str
    balance_cents: int = Field(..., alias="balanceCents")
    value_base_cents: int = Field(..., alias="valueBaseCents")
    rate: float
    primary: bool

    model_config = ConfigDict(populate_by_name=True)


class AvailableCurrency(BaseModel):
    """An entry in the supported-currency catalogue."""

    code: str
    name: str
    flag: str

    model_config = ConfigDict(populate_by_name=True)


class WalletCurrenciesOut(BaseModel):
    """The multi-currency wallet view: holdings + the currency catalogue."""

    base_currency: str = Field(..., alias="baseCurrency")
    total_value_base_cents: int = Field(..., alias="totalValueBaseCents")
    holdings: list[CurrencyHolding] = Field(default_factory=list)
    available_currencies: list[AvailableCurrency] = Field(
        default_factory=list, alias="availableCurrencies"
    )
    is_demo: bool = Field(..., alias="isDemo")
    note: str

    model_config = ConfigDict(populate_by_name=True)


class ConvertRequest(BaseModel):
    """Smart-conversion preview request (no real money movement)."""

    from_currency: str = Field(
        ..., alias="fromCurrency", min_length=3, max_length=3
    )
    to_currency: str = Field(..., alias="toCurrency", min_length=3, max_length=3)
    amount_cents: int = Field(..., alias="amountCents", gt=0, le=1_000_000_000)

    model_config = ConfigDict(populate_by_name=True)


class ConvertOut(BaseModel):
    """Smart-conversion preview result at live rates (display only)."""

    from_currency: str = Field(..., alias="fromCurrency")
    to_currency: str = Field(..., alias="toCurrency")
    from_amount_cents: int = Field(..., alias="fromAmountCents")
    to_amount_cents: int = Field(..., alias="toAmountCents")
    rate: float
    fee_pct: float = Field(..., alias="feePct")
    is_demo: bool = Field(..., alias="isDemo")

    model_config = ConfigDict(populate_by_name=True)
