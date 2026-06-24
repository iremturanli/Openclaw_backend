"""PaxPal: issued cards + shared expense groups (bill splitting / settle up)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-10 17:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'pax_cards',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('guest_id', sa.String(length=64), nullable=False),
        sa.Column('label', sa.String(length=64), nullable=False),
        sa.Column('holder', sa.String(length=255), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('last4', sa.String(length=4), nullable=False),
        sa.Column('color', sa.String(length=9), nullable=False),
        sa.Column('frozen', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('programmed', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pax_cards_guest_id', 'pax_cards', ['guest_id'])

    op.create_table(
        'expense_groups',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'group_members',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('group_id', sa.String(length=64),
                  sa.ForeignKey('expense_groups.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('guest_id', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('group_id', 'guest_id', name='uq_group_member'),
    )
    op.create_index('ix_group_members_group_id', 'group_members', ['group_id'])

    op.create_table(
        'group_expenses',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('group_id', sa.String(length=64),
                  sa.ForeignKey('expense_groups.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('payer_guest_id', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('amount_cents', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('settled', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_group_expenses_group_id', 'group_expenses',
                    ['group_id'])


def downgrade() -> None:
    op.drop_table('group_expenses')
    op.drop_table('group_members')
    op.drop_table('expense_groups')
    op.drop_table('pax_cards')
