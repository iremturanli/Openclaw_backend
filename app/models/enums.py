"""Enumerations shared across the API models."""

from __future__ import annotations

from enum import Enum


class Sex(str, Enum):
    """Guest sex as exposed by the API.

    The Flutter app maps the raw MRZ character to these JSON values:
    ``M -> male``, ``F -> female``, ``X``/``<`` -> ``unspecified``.
    """

    MALE = "male"
    FEMALE = "female"
    UNSPECIFIED = "unspecified"


class CheckInStatus(str, Enum):
    """Lifecycle status of a check-in.

    * ``pending``  - submitted, verification not yet complete.
    * ``verified`` - identity accepted, digital key issued.
    * ``rejected`` - check-in refused (e.g. expired passport).
    """

    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class OrderStatus(str, Enum):
    """Lifecycle status of a room-service order.

    Matches the ``status`` enum in ``docs/api_contract.md``. New orders start as
    ``placed``; the remaining values model fulfilment progress.
    """

    PLACED = "placed"
    PREPARING = "preparing"
    ON_THE_WAY = "onTheWay"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
