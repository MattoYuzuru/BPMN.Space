"""Публичными на чтение остаются только демо-проекты из сида.

Раньше проект без владельца автоматически становился `public_read_only`, и всё, что создали
при выключенной авторизации, открывалось любому вошедшему пользователю. Миграция закрывает
такие проекты; идентификаторы демо-проектов детерминированы (`app/infra/seed.py`) и
зафиксированы здесь, чтобы миграция не менялась вместе с сидом.

Revision ID: 0006_public_only_demo_projects
Revises: 0005_auth_and_sharing
"""

from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "0006_public_only_demo_projects"
down_revision = "0005_auth_and_sharing"
branch_labels = None
depends_on = None

SEED_PROJECT_IDS = (
    "55323c54-3524-5676-abfd-01f834ddad13",
    "517a2188-3811-5465-bb49-a67c9421c1c1",
    "fe0525b5-a851-5e2b-aa6c-076c151fa864",
    "5eb2b5d4-4562-5649-8990-0a4f3b19f68f",
    "99f84f04-0698-55f7-8d0e-8fb8ef2fa480",
    "2bbf0a25-34f9-59ee-8fc9-dc00612ddcdc",
    "721ca861-945c-5530-8b6b-fa1183ff7d78",
    "1b65bb03-a466-5ff6-a945-da52f15c41a1",
    "1cab69d7-3a0f-5d39-8b99-3a0e8a268516",
    "8409c2a7-8899-546e-b932-b845c165ddaf",
    "25e5d4cd-871e-5e0f-8048-ecaac1bea9ad",
    "4e4dfd0a-a1dd-57f3-8769-5acecfe28f11",
    "d4608e03-c62e-51cd-b6d9-4f6611aa00b7",
    "4d2ec2ba-d287-5d13-8ff7-b4738a1f28a2",
    "0189ee86-3aac-5f07-b0d2-6076f10d3053",
    "de63d57a-0f63-5941-a2dd-22e887acd94e",
    "9867d8dd-66d4-5bf6-ae63-ac417127cb1e",
    "21777948-7f3b-51be-9108-7bb411865ddf",
    "b8fa004c-22a3-53dc-b17a-8efa4ef59b93",
    "3e4b53f0-eb1c-55f9-8ebf-d150f4aae3c1",
    "e9c75948-333f-5868-82b8-3d9a96c25ff3",
    "c6fbd46f-0710-5dd9-8038-433814d5feb0",
    "c6944d6c-5b46-5d11-aae4-b9ae24d457d1",
    "c1565257-a5de-506d-90a5-07e8eb300261",
    "65cdc6ac-31b0-589f-b304-f80edf274922",
    "a34e7652-da82-5c16-b11b-8933a157f3e2",
    "be398df6-bdc3-5526-a471-cb4b199c94d1",
    "d7f93fee-cc2f-5d8f-9b6d-829cfbcdabb3",
    "44e0403b-8684-559e-886e-872de395610f",
    "07656b10-6713-5cd3-983e-2bbff9e79220",
    "e2a51cf6-f75a-5a31-8dd7-97c5e6415e79",
    "71527462-2192-5b87-926e-1807da207c0c",
    "250d6a56-c960-5f85-b554-49365ebce9bb",
    "5ffa26b3-8fa8-5638-ba6b-1357f98c5687",
    "68e3b51a-7d82-5e57-841c-99280548097f",
    "6f2d4e72-ba0b-5ebc-9781-a295a7cbfe76",
    "a3177d83-3e1a-5f85-9ff5-4832bd6d0d49",
    "6133780c-2cff-5c92-975e-e0aae7d12a60",
    "666b90b0-8a52-54c2-a9a4-4d9a457bb878",
    "a27bc6f3-e380-534f-a148-fbc06765765e",
    "5be58684-126a-5d2b-bc2a-76f72d88a1c7",
)


def upgrade() -> None:
    projects = sa.table(
        "projects", sa.column("id", sa.Uuid()), sa.column("public_read_only", sa.Boolean())
    )
    op.execute(
        projects.update()
        .where(projects.c.id.not_in([UUID(item) for item in SEED_PROJECT_IDS]))
        .values(public_read_only=False)
    )


def downgrade() -> None:
    # Закрытый доступ обратно не открываем: это изменение безопасности.
    pass
