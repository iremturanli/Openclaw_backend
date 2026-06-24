"""Wire schemas for PaxPal: cards, expense groups, settle-up and live FX."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── Cards ─────────────────────────────────────────────────────────────────
class PaxCardOut(BaseModel):
    id: str
    label: str
    holder: str
    kind: str
    last4: str
    color: str
    frozen: bool
    programmed: bool
    contactless: bool
    international: bool
    atm: bool
    monthly_limit_cents: int = Field(..., alias="monthlyLimitCents")
    created_at: datetime = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class CardControlsRequest(BaseModel):
    """Partial update of a card's security/spending controls."""

    contactless: bool | None = None
    international: bool | None = None
    atm: bool | None = None
    monthly_limit_cents: int | None = Field(
        default=None, alias="monthlyLimitCents", gt=0, le=100_000_000
    )

    model_config = ConfigDict(populate_by_name=True)


class IssueCardRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    kind: str = Field(default="virtual", pattern="^(virtual|physical)$")
    color: str = Field(default="#2667F2", max_length=9)

    model_config = ConfigDict(populate_by_name=True)


class ProgramCardResponse(BaseModel):
    card_id: str = Field(..., alias="cardId")
    token: str
    programmed: bool

    model_config = ConfigDict(populate_by_name=True)


# ── Expense groups / settle up ────────────────────────────────────────────
class GroupMemberOut(BaseModel):
    guest_id: str = Field(..., alias="guestId")
    display_name: str = Field(..., alias="displayName")
    paid_cents: int = Field(..., alias="paidCents")
    share_cents: int = Field(..., alias="shareCents")
    # positive = is owed money, negative = owes money.
    net_cents: int = Field(..., alias="netCents")

    model_config = ConfigDict(populate_by_name=True)


class GroupExpenseOut(BaseModel):
    id: str
    title: str
    payer_guest_id: str = Field(..., alias="payerGuestId")
    payer_name: str = Field(..., alias="payerName")
    amount_cents: int = Field(..., alias="amountCents")
    currency: str
    settled: bool
    created_at: datetime = Field(..., alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class GroupOut(BaseModel):
    id: str
    name: str
    total_cents: int = Field(..., alias="totalCents")
    unsettled_cents: int = Field(..., alias="unsettledCents")
    currency: str = "USD"
    members: list[GroupMemberOut] = Field(default_factory=list)
    expenses: list[GroupExpenseOut] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class AddExpenseRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    amount_cents: int = Field(..., alias="amountCents", gt=0)

    model_config = ConfigDict(populate_by_name=True)


class SettleTransferOut(BaseModel):
    to_guest_id: str = Field(..., alias="toGuestId")
    to_name: str = Field(..., alias="toName")
    amount_cents: int = Field(..., alias="amountCents")

    model_config = ConfigDict(populate_by_name=True)


class SettleResponse(BaseModel):
    transfers: list[SettleTransferOut] = Field(default_factory=list)
    balance_cents: int = Field(..., alias="balanceCents")
    settled_cents: int = Field(..., alias="settledCents")

    model_config = ConfigDict(populate_by_name=True)


# ── Live FX ───────────────────────────────────────────────────────────────
class FxRatesOut(BaseModel):
    base: str
    date: str
    rates: dict[str, float]
    provider: str = "frankfurter.dev"

    model_config = ConfigDict(populate_by_name=True)
