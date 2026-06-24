"""PaxCard security controls + monthly spending limit

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-11 09:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: str | None = 'c3d4e5f6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('pax_cards', sa.Column(
        'contactless', sa.Boolean(), nullable=False,
        server_default=sa.text('true')))
    op.add_column('pax_cards', sa.Column(
        'international', sa.Boolean(), nullable=False,
        server_default=sa.text('true')))
    op.add_column('pax_cards', sa.Column(
        'atm', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('pax_cards', sa.Column(
        'monthly_limit_cents', sa.BigInteger(), nullable=False,
        server_default=sa.text('500000')))


def downgrade() -> None:
    op.drop_column('pax_cards', 'monthly_limit_cents')
    op.drop_column('pax_cards', 'atm')
    op.drop_column('pax_cards', 'international')
    op.drop_column('pax_cards', 'contactless')
