from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.routes import Projects
from app.models.entities import ChangeSet
from app.schemas.domain import ProjectView
from app.schemas.workspace import FileWrite, PathAction, WorkspaceCreate
from app.security.policy import SafetyViolation
from app.services.checkpoints import CheckpointStore
from app.services.diagnostics import DiagnosticsService
from app.services.hooks import HookService
from app.services.workspace_files import WorkspaceFiles

router = APIRouter()


def files(request: Request) -> WorkspaceFiles:
    return request.app.state.files  # type: ignore[no-any-return]


Files = Annotated[WorkspaceFiles, Depends(files)]


@router.get("/workspace/options")
def workspace_options(service: Projects) -> dict[str, Any]:
    return {"roots": [str(root) for root in service.settings.workspace_roots],
            "templates": ["empty", "python", "fastapi", "node", "next", "react"],
            "default_location": "Forge workspaces", "managed_location": str(service.settings.data_directory / "projects")}


@router.post("/projects/new", response_model=ProjectView)
def create_workspace(body: WorkspaceCreate, service: Projects) -> ProjectView:
    return service.create(body)


@router.get("/projects/{project_id}/tree")
def directory_tree(project_id: str, service: Projects, filesystem: Files) -> list[dict[str, str]]:
    return filesystem.tree(service.get(project_id))


@router.post("/projects/{project_id}/files/write")
def write_file(project_id: str, body: FileWrite, service: Projects, filesystem: Files) -> dict[str, Any]:
    result = filesystem.write(service.get(project_id), body.path, body.content, body.base_hash)
    service.refresh(project_id)
    try:
        result["hooks"] = HookService(service.settings).queue(service.get(project_id), "AfterFileEdit")
    except (ValueError, SafetyViolation, OSError):
        result["hooks_error"] = "Source saved. Hook configuration could not be loaded."
    return result


@router.post("/projects/{project_id}/folders")
def create_folder(project_id: str, body: PathAction, service: Projects, filesystem: Files) -> dict[str, str]:
    filesystem.mkdir(service.get(project_id), body.path)
    service.refresh(project_id)
    return {"path": body.path, "status": "created"}


@router.post("/projects/{project_id}/files/move")
def move_file(project_id: str, body: PathAction, service: Projects, filesystem: Files) -> dict[str, str]:
    if not body.destination:
        raise SafetyViolation("A destination is required")
    filesystem.move(service.get(project_id), body.path, body.destination)
    service.refresh(project_id)
    return {"path": body.destination, "status": "moved"}


@router.post("/projects/{project_id}/files/trash")
def trash_file(project_id: str, body: PathAction, service: Projects, filesystem: Files) -> dict[str, str]:
    key = filesystem.trash(service.get(project_id), body.path)
    service.refresh(project_id)
    return {"trash_id": key, "status": "trashed"}


@router.post("/projects/{project_id}/trash/{trash_id}/restore")
def restore_file(project_id: str, trash_id: str, service: Projects, filesystem: Files) -> dict[str, str]:
    path = filesystem.restore(service.get(project_id), trash_id)
    service.refresh(project_id)
    return {"path": path, "status": "restored"}


@router.get("/projects/{project_id}/search")
def search_text(project_id: str, service: Projects, filesystem: Files,
                q: str = Query(min_length=1, max_length=500), include: str = "*", exclude: str = "") -> dict[str, Any]:
    hits = filesystem.search(service.get(project_id), q, include[:500], exclude[:500])
    return {"hits": hits, "truncated": len(hits) == 200}


@router.get("/projects/{project_id}/symbols")
def search_symbols(project_id: str, service: Projects, q: str = "") -> list[dict[str, Any]]:
    project = service.get(project_id)
    return [symbol.model_dump() for symbol in project.project_map.symbols if q.lower() in symbol.name.lower()][:200]


@router.get("/projects/{project_id}/diagnostics")
def diagnostics(project_id: str, service: Projects) -> dict[str, Any]:
    return {"problems": DiagnosticsService(service.settings).inspect(service.get(project_id)), "evidence": "VERIFIED", "scope": "syntax"}


@router.post("/projects/{project_id}/format")
async def format_draft(project_id: str, body: FileWrite, service: Projects) -> dict[str, str]:
    content = await DiagnosticsService(service.settings).format(service.get(project_id), body.path, body.content)
    return {"content": content, "status": "formatted", "evidence": "VERIFIED"}


@router.post("/editor/format")
async def format_scratch(body: FileWrite, service: Projects) -> dict[str, str]:
    return {"content": await DiagnosticsService(service.settings).format(None, body.path, body.content), "evidence": "VERIFIED"}


@router.get("/projects/{project_id}/checkpoints")
def checkpoints(project_id: str, service: Projects) -> list[dict[str, Any]]:
    return CheckpointStore(service.settings).list(service.get(project_id))


@router.post("/projects/{project_id}/checkpoints/{checkpoint_id}/restore")
def restore_checkpoint(project_id: str, checkpoint_id: str, service: Projects) -> dict[str, Any]:
    project = service.get(project_id)
    restored = CheckpointStore(service.settings).restore(project, checkpoint_id)
    with service.sessions.begin() as session:
        change = session.get(ChangeSet, restored["change_id"])
        if change is not None:
            change.status = "restored"
    service.refresh(project_id)
    return restored


@router.get("/projects/{project_id}/checkpoints/{checkpoint_id}")
def checkpoint_details(project_id: str, checkpoint_id: str, service: Projects) -> dict[str, Any]:
    return CheckpointStore(service.settings).load(service.get(project_id), checkpoint_id)
