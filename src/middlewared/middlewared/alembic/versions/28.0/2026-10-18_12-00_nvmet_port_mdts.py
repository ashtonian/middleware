"""NVMe-oF port maximum data transfer size

Revision ID: d5b7b7c0dc05
Revises: d5e404a65f70
Create Date: 2026-10-18 12:00:00.000000+00:00

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d5b7b7c0dc05"
down_revision = "d5e404a65f70"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("services_nvmet_port", schema=None) as batch_op:
        batch_op.add_column(sa.Column("nvmet_port_max_data_transfer_size", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("services_nvmet_port", schema=None) as batch_op:
        batch_op.drop_column("nvmet_port_max_data_transfer_size")
