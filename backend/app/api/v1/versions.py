"""Версии схемы: список, XML, скачивание, ручная правка."""

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.access import ensure_project_access, ensure_resource_access
from app.api.auth import OptionalUserDep
from app.api.deps import ContainerDep
from app.api.schemas.common import errors
from app.api.schemas.versions import DiagramSave, Version, VersionDetail

router = APIRouter(tags=["versions"])


@router.get("/projects/{project_id}/versions", responses=errors(404, 422))
async def list_versions(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> list[Version]:
    """Версии без XML, последняя — первой."""
    await ensure_project_access(request, container, project_id, user, write=False)
    return [Version.model_validate(v) for v in await container.versions.list(project_id)]


@router.get("/versions/{version_id}", responses=errors(404, 422))
async def get_version(
    version_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> VersionDetail:
    await ensure_resource_access(
        request, container, version_id, user, resource="version", write=False
    )
    return VersionDetail.model_validate(await container.versions.get(version_id))


@router.get(
    "/versions/{version_id}/xml",
    response_class=Response,
    responses={
        200: {"content": {"application/xml": {}}, "description": "BPMN 2.0 XML файлом"},
        **errors(404, 422),
    },
)
async def download_version(
    version_id: UUID,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Response:
    """Скачать `.bpmn` (Content-Disposition: attachment)."""
    await ensure_resource_access(
        request, container, version_id, user, resource="version", write=False
    )
    version = await container.versions.get(version_id)
    project = await container.projects.get(version.project_id)
    name = f"{project.project.title} v{version.number}.bpmn"
    disposition = (
        f"attachment; filename=\"diagram-v{version.number}.bpmn\"; filename*=UTF-8''{quote(name)}"
    )
    return Response(
        content=version.xml,
        media_type="application/xml",
        headers={"Content-Disposition": disposition},
    )


@router.put(
    "/projects/{project_id}/diagram",
    status_code=status.HTTP_201_CREATED,
    responses=errors(404, 413, 422),
)
async def save_diagram(
    project_id: UUID,
    body: DiagramSave,
    request: Request,
    container: ContainerDep,
    user: OptionalUserDep,
) -> Version:
    """Сохранить правку из bpmn-js как новую версию `manual`."""
    await ensure_project_access(request, container, project_id, user, write=True)
    return Version.model_validate(await container.versions.save_manual(project_id, xml=body.xml))
