"""Компактные версии XML; старые снимки читаются без преобразования при миграции."""

import sqlalchemy as sa
from alembic import op

revision = "0011_compact_versions"
down_revision = "0010_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("diagram_versions", "bpmn_xml", nullable=True)
    op.add_column("diagram_versions", sa.Column("packed_xml", sa.LargeBinary(), nullable=True))
    op.add_column("diagram_versions", sa.Column("xml_sha256", sa.String(64), nullable=True))
    op.add_column("diagram_versions", sa.Column("base_version_id", sa.Uuid(), nullable=True))
    op.add_column(
        "diagram_versions",
        sa.Column("storage_depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_versions_storage_base",
        "diagram_versions",
        "diagram_versions",
        ["base_version_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_index("ix_diagram_versions_base_version_id", "diagram_versions", ["base_version_id"])
    op.create_check_constraint(
        "ck_versions_storage_depth", "diagram_versions", "storage_depth BETWEEN 0 AND 20"
    )
    op.create_check_constraint(
        "ck_versions_storage_format",
        "diagram_versions",
        "(bpmn_xml IS NOT NULL AND packed_xml IS NULL AND xml_sha256 IS NULL "
        "AND base_version_id IS NULL AND storage_depth = 0) OR "
        "(bpmn_xml IS NULL AND packed_xml IS NOT NULL AND xml_sha256 IS NOT NULL AND "
        "((base_version_id IS NULL AND storage_depth = 0) OR "
        "(base_version_id IS NOT NULL AND storage_depth > 0)))",
    )


def downgrade() -> None:
    # Удаление packed_xml без восстановления XML уничтожило бы историю.
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM diagram_versions WHERE bpmn_xml IS NULL)")
    ):
        raise RuntimeError("Сначала выполните python -m app.infra.version_maintenance --restore")
    op.drop_constraint("ck_versions_storage_format", "diagram_versions", type_="check")
    op.drop_constraint("ck_versions_storage_depth", "diagram_versions", type_="check")
    op.drop_index("ix_diagram_versions_base_version_id", table_name="diagram_versions")
    op.drop_constraint("fk_versions_storage_base", "diagram_versions", type_="foreignkey")
    for column in ("storage_depth", "base_version_id", "xml_sha256", "packed_xml"):
        op.drop_column("diagram_versions", column)
    op.alter_column("diagram_versions", "bpmn_xml", nullable=False)
