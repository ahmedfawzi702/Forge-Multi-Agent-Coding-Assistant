from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.code_intelligence.repository_scanner import ProjectScanner
from app.config import Settings
from app.models.entities import Project, ProjectIndexMetadata, ProjectMemory
from app.schemas.domain import ProjectMap, ProjectView
from app.schemas.engineering import ProjectImport
from app.schemas.workspace import WorkspaceCreate
from app.security.paths import safe_target
from app.security.policy import SafetyViolation
from app.services.imports import import_snapshot
from app.services.templates import template_files


class ProjectNotFound(LookupError):
    pass


class ProjectService:
    def __init__(self, settings: Settings, sessions: sessionmaker[Session]):
        self.settings = settings
        self.sessions = sessions
        self.scanner = ProjectScanner(settings)

    def open(self, raw_path: str, *, imported: bool = False, display_name: str | None = None,
             source_kind: Literal["local", "browser", "managed"] | None = None) -> ProjectView:
        scanner = self.scanner
        kind: Literal["local", "browser", "managed"] = "browser" if imported else source_kind or "local"
        if kind in {"browser", "managed"}:
            candidate = Path(raw_path).resolve(strict=True)
            container = "imports" if kind == "browser" else "projects"
            if candidate.parent != (self.settings.data_directory / container).resolve():
                raise SafetyViolation("Invalid managed snapshot")
            scanner = ProjectScanner(self.settings.model_copy(update={"workspace_roots": [candidate]}))
        root = scanner.validate_root(raw_path)
        project_map = scanner.scan(root)
        project_map.source_kind = kind
        with self.sessions.begin() as session:
            project = session.scalar(select(Project).where(Project.path == str(root)))
            if project is None:
                project = Project(name=display_name or root.name, path=str(root), project_map=project_map.model_dump())
                session.add(project)
                session.flush()
            else:
                project.project_map = project_map.model_dump()
            metadata = session.scalar(select(ProjectIndexMetadata).where(ProjectIndexMetadata.project_id == project.id))
            index = {"scanned_at": project_map.scanned_at, "file_count": len(project_map.files), "parser": "python_ast+tree_sitter"}
            if metadata:
                metadata.metadata_value = index
            else:
                session.add(ProjectIndexMetadata(project_id=project.id, metadata_value=index))
            memory = session.scalar(select(ProjectMemory).where(
                ProjectMemory.project_id == project.id, ProjectMemory.category == "facts", ProjectMemory.key == "scan"))
            facts = {"languages": project_map.language, "frameworks": project_map.framework,
                     "directories": project_map.important_directories, "scanned_at": project_map.scanned_at}
            if memory:
                memory.value = facts
            else:
                session.add(ProjectMemory(project_id=project.id, category="facts", key="scan", value=facts,
                                          source="Manifest and filesystem scan; not conversation claims"))
            return ProjectView(id=project.id, name=project.name, path=project.path, project_map=project_map,
                               source_kind=project_map.source_kind)

    def import_project(self, request: ProjectImport) -> ProjectView:
        root = import_snapshot(self.settings.data_directory / "imports", request, self.settings.max_file_bytes)
        return self.open(str(root), imported=True, display_name=request.name)

    def create(self, request: WorkspaceCreate) -> ProjectView:
        if request.location:
            parent = self.scanner.validate_root(request.location)
            root = safe_target(parent, request.name)
            if root.parent != parent:
                raise SafetyViolation("Project name must be a single folder name")
            kind: Literal["local", "managed"] = "local"
        else:
            parent = self.settings.data_directory / "projects"
            parent.mkdir(parents=True, exist_ok=True)
            # Still validate names before displaying or writing template metadata.
            if safe_target(parent, request.name).parent != parent:
                raise SafetyViolation("Project name must be a single folder name")
            root = parent / str(uuid4())
            kind = "managed"
        if root.exists():
            raise SafetyViolation("Project folder already exists; open it instead")
        root.mkdir()
        for path, content in template_files(request.template, request.name).items():
            target = safe_target(root, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return self.open(str(root), display_name=request.name, source_kind=kind)

    def refresh(self, project_id: str) -> ProjectView:
        project = self.get(project_id)
        return self.open(project.path, display_name=project.name, source_kind=project.source_kind)

    def get(self, project_id: str) -> ProjectView:
        with self.sessions() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise ProjectNotFound("Project not found")
            project_map = ProjectMap.model_validate(project.project_map)
            if project_map.source_kind in {"browser", "managed"}:
                candidate = Path(project.path).resolve(strict=True)
                container = "imports" if project_map.source_kind == "browser" else "projects"
                if candidate.parent != (self.settings.data_directory / container).resolve():
                    raise SafetyViolation("Invalid managed snapshot")
                ProjectScanner(self.settings.model_copy(update={"workspace_roots": [candidate]})).validate_root(project.path)
            else:
                self.scanner.validate_root(project.path)
            return ProjectView(id=project.id, name=project.name, path=project.path,
                               project_map=project_map, source_kind=project_map.source_kind)

    def list(self) -> list[dict[str, str]]:
        with self.sessions() as session:
            return [{"id": p.id, "name": p.name, "path": p.path}
                    for p in session.scalars(select(Project).order_by(Project.created_at.desc()))
                    if any(Path(p.path).is_relative_to(root) for root in self.settings.workspace_roots)
                    or p.project_map.get("source_kind") in {"browser", "managed"} and Path(p.path).resolve().parent ==
                    (self.settings.data_directory / ("imports" if p.project_map.get("source_kind") == "browser" else "projects")).resolve()]
