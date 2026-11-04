"""Производные источники и дерево материалов (RFC-0006, шаг 3).

Новые поля `sources`: `origin`, `parent_id` (родитель того же проекта, каскадное удаление),
`derivation`, `trust`, `edited_by_human`, `media`. Существующие ответы на вопросы получают
`origin=answer`, прочие — `origin=user`; все — `trust=primary`. Старые записи с
расшифровкой в самом источнике остаются одним узлом: текст и цитаты не переезжают.

Откат не теряет данных: текст, статус и ошибка расшифровки возвращаются в запись (как до
0016), цитаты вопросов и версий переводятся на запись, и только потом строки расшифровок
удаляются. Производные узлы, которые так свернуть нельзя, — явный отказ отката.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_source_derivation"
down_revision = "0015_version_sessions"
branch_labels = None
depends_on = None

_CHECKS = {
    "ck_sources_origin": "origin IN ('user', 'derived', 'agent', 'answer')",
    "ck_sources_trust": (
        "trust IN ('primary', 'extracted', 'observed', 'external', 'agent', 'summary')"
    ),
    "ck_sources_not_own_parent": "parent_id <> id",
}

# Расшифровка, которую можно свернуть обратно в запись: прямой потомок с speech_to_text.
_TRANSCRIPT = (
    "c.parent_id IS NOT NULL AND c.derivation->>'capability' = 'speech_to_text' "
    "AND NOT EXISTS (SELECT 1 FROM sources g WHERE g.parent_id = c.id)"
)


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("origin", sa.String(16), nullable=False, server_default="user"),
    )
    op.add_column("sources", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.add_column("sources", sa.Column("derivation", postgresql.JSONB(), nullable=True))
    op.add_column(
        "sources",
        sa.Column("trust", sa.String(16), nullable=False, server_default="primary"),
    )
    op.add_column(
        "sources",
        sa.Column("edited_by_human", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("sources", sa.Column("media", postgresql.JSONB(), nullable=True))
    op.execute("UPDATE sources SET origin = 'answer' WHERE kind = 'answer'")
    op.create_unique_constraint("uq_sources_id_project", "sources", ["id", "project_id"])
    # NOT VALID + VALIDATE: проверка существующих строк отдельным шагом с более слабой
    # блокировкой; откат не меняется — DROP CONSTRAINT одинаков для обоих вариантов.
    op.execute(
        "ALTER TABLE sources ADD CONSTRAINT fk_sources_parent_same_project "
        "FOREIGN KEY (parent_id, project_id) REFERENCES sources (id, project_id) "
        "ON DELETE CASCADE NOT VALID"
    )
    for name, condition in _CHECKS.items():
        op.execute(f"ALTER TABLE sources ADD CONSTRAINT {name} CHECK ({condition}) NOT VALID")
    for name in ("fk_sources_parent_same_project", *_CHECKS):
        op.execute(f"ALTER TABLE sources VALIDATE CONSTRAINT {name}")
    op.create_index("ix_sources_parent_id", "sources", ["parent_id"])


def _refuse_lossy_downgrade() -> None:
    connection = op.get_bind()
    blocked = connection.execute(
        sa.text(
            f"""
            SELECT count(*) FROM sources c
            WHERE c.parent_id IS NOT NULL AND NOT ({_TRANSCRIPT})
            """  # noqa: S608 — условие — константа модуля
        )
    ).scalar_one()
    crowded = connection.execute(
        sa.text(
            f"""
            SELECT count(*) FROM (
                SELECT c.parent_id FROM sources c WHERE {_TRANSCRIPT}
                GROUP BY c.parent_id HAVING count(*) > 1
            ) AS many
            """  # noqa: S608 — условие — константа модуля
        )
    ).scalar_one()
    occupied = connection.execute(
        sa.text(
            f"""
            SELECT count(*) FROM sources c JOIN sources p ON p.id = c.parent_id
            WHERE {_TRANSCRIPT} AND p.content <> ''
            """  # noqa: S608 — условие — константа модуля
        )
    ).scalar_one()
    if blocked or crowded or occupied:
        raise RuntimeError(
            "Откат 0016 потерял бы производные источники: "
            f"не-расшифровок {blocked}, записей с несколькими расшифровками {crowded}, "
            f"записей со своим текстом {occupied}. Удалите или перенесите их вручную"
        )


def downgrade() -> None:
    _refuse_lossy_downgrade()
    # Цитаты вопросов и версий указывают на расшифровку: после отката текст лежит в записи.
    for column in ("about", "evidence"):
        op.execute(
            f"""
            UPDATE questions q
            SET {column} = jsonb_set(q.{column}, '{{source_id}}', to_jsonb(c.parent_id::text))
            FROM sources c
            WHERE {_TRANSCRIPT} AND q.{column}->>'source_id' = c.id::text
            """  # noqa: S608 — имена колонок — константы
        )
    op.execute(
        f"""
        UPDATE diagram_versions v
        SET trace = (
            SELECT jsonb_object_agg(
                t.key,
                CASE WHEN c.id IS NULL THEN t.value
                     ELSE jsonb_set(t.value, '{{source_id}}', to_jsonb(c.parent_id::text)) END
            )
            FROM jsonb_each(v.trace) AS t(key, value)
            LEFT JOIN sources c ON c.id::text = t.value->>'source_id' AND {_TRANSCRIPT}
        )
        WHERE EXISTS (
            SELECT 1 FROM jsonb_each(v.trace) AS t(key, value)
            JOIN sources c ON c.id::text = t.value->>'source_id'
            WHERE {_TRANSCRIPT}
        )
        """  # noqa: S608 — условие — константа модуля
    )
    # Запись получает текст, статус, ошибку и длительность расшифровки — как до 0016.
    op.execute(
        f"""
        UPDATE sources p
        SET content = c.content,
            status = c.status,
            error = c.error,
            warning = c.warning,
            duration_sec = COALESCE(c.duration_sec, p.duration_sec),
            active = p.active AND c.active
        FROM sources c
        WHERE c.parent_id = p.id AND {_TRANSCRIPT}
        """  # noqa: S608 — условие — константа модуля
    )
    op.execute(f"DELETE FROM sources c WHERE {_TRANSCRIPT}")  # noqa: S608
    op.drop_index("ix_sources_parent_id", table_name="sources")
    for name in _CHECKS:
        op.drop_constraint(name, "sources", type_="check")
    op.drop_constraint("fk_sources_parent_same_project", "sources", type_="foreignkey")
    op.drop_constraint("uq_sources_id_project", "sources", type_="unique")
    for column in ("media", "edited_by_human", "trust", "derivation", "parent_id", "origin"):
        op.drop_column("sources", column)
