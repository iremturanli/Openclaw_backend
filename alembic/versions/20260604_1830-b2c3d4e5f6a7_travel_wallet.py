"""travel budget wallet + purchases

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-04 18:30:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'wallet_budgets',
        sa.Column('guest_id', sa.String(length=64), nullable=False),
        sa.Column('balance_cents', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('guest_id'),
    )
    op.create_table(
        'purchases',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('guest_id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('subtitle', sa.String(length=512), nullable=False),
        sa.Column('amount_cents', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_purchases_guest_id', 'purchases', ['guest_id'])
    op.create_index('ix_purchases_kind', 'purchases', ['kind'])


def downgrade() -> None:
    op.drop_index('ix_purchases_kind', table_name='purchases')
    op.drop_index('ix_purchases_guest_id', table_name='purchases')
    op.drop_table('purchases')
    op.drop_table('wallet_budgets')
