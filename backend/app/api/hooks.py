from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.api.routes import Projects
from app.execution.file_io import atomic_write
from app.security.paths import safe_target
from app.services.hooks import HookConfig, HookService

router = APIRouter()


@router.get("/projects/{project_id}/hooks")
def hooks(project_id: str, service: Projects) -> dict[str, Any]:
    project = service.get(project_id)
    hooks = HookService(service.settings)
    return {"hooks": [hook.model_dump() for hook in hooks.configuration(project)], "runs": hooks.history(project)}


@router.post("/projects/{project_id}/hooks/config")
def configure(project_id: str, body: HookConfig, service: Projects) -> dict[str, str]:
    project = service.get(project_id)
    atomic_write(safe_target(Path(project.path), ".forge/hooks.json"), body.model_dump_json(indent=2))
    return {"status": "saved"}


@router.post("/projects/{project_id}/hooks/{hook_id}/run")
async def run_hook(project_id: str, hook_id: str, body: dict[str, bool], service: Projects) -> dict[str, Any]:
    return await HookService(service.settings).run(service.get(project_id), hook_id, approved=body.get("approved", False))
