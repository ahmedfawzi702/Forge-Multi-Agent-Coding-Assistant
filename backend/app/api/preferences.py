from typing import Any

from fastapi import APIRouter

from app.api.routes import Projects
from app.services.preferences import Preferences, PreferenceStore
from app.services.rules import RulesLoader

router = APIRouter()


@router.get("/preferences")
def global_preferences(service: Projects) -> dict[str, Any]:
    return PreferenceStore(service.settings).load().model_dump()


@router.post("/preferences")
def save_global_preferences(body: Preferences, service: Projects) -> dict[str, Any]:
    return PreferenceStore(service.settings).save(body).model_dump()


@router.get("/projects/{project_id}/preferences")
def project_preferences(project_id: str, service: Projects) -> dict[str, Any]:
    from pathlib import Path
    project = service.get(project_id)
    store = PreferenceStore(service.settings)
    return {"local": store.load(project_id).model_dump(), "effective": store.effective(project_id).model_dump(),
            "rules": RulesLoader(Path(project.path)).load([file.path for file in project.project_map.files[:100]])}


@router.post("/projects/{project_id}/preferences")
def save_project_preferences(project_id: str, body: Preferences, service: Projects) -> dict[str, Any]:
    service.get(project_id)
    return PreferenceStore(service.settings).save(body, project_id).model_dump()
