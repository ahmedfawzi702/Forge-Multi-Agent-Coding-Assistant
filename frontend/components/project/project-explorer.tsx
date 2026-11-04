"use client";
import { FolderOpen, RefreshCw, ChevronDown, ShieldCheck, Files, FilePlus2, FolderPlus } from "lucide-react";
import { FileTree, type ExplorerAction } from "@/components/file-tree";
import type { Project, FileEntry } from "@/types";

export function ProjectExplorer({ project, active, busy, onOpen, onRefresh, onBrowse, files, directories, onAction }: { project: Project | null; active: string; busy: boolean; onOpen: (path: string) => void; onRefresh: () => void; onBrowse: () => void; files?: FileEntry[]; directories?: string[]; onAction?: (action: ExplorerAction, path: string, directory: boolean) => void }) {
  return <div className="explorer"><div className="panel-title"><div><Files size={13} /><span className="eyebrow">EXPLORER</span></div><div>{project && <><button className="icon-button" aria-label="New workspace file" onClick={() => onAction?.("file", "", true)}><FilePlus2 size={13} /></button><button className="icon-button" aria-label="New folder" onClick={() => onAction?.("folder", "", true)}><FolderPlus size={13} /></button></>}<button className="icon-button" disabled={!project || busy} onClick={onRefresh} aria-label="Refresh project index"><RefreshCw size={13} className={busy ? "spin" : ""} /></button></div></div>
    <div className="project-tree-title"><ChevronDown size={12} /><span>{project?.name || "YOUR WORKSPACE"}</span>{project && <span className="count-badge">{project.project_map.files.length}</span>}</div>
    {project ? <FileTree files={files || project.project_map.files} directories={directories || project.project_map.directories} selected={active} onOpen={onOpen} onAction={onAction} /> : <div className="explorer-empty"><FolderOpen size={24} /><p>Scratch files work without a project.</p><button onClick={onBrowse}>Browse folder</button></div>}
    <div className="explorer-bottom"><ShieldCheck size={14} /><div><strong>{project?.source_kind === "browser" ? "Imported snapshot" : "Local workspace"}</strong><span>{project?.source_kind === "browser" ? "Edits save to this snapshot" : "Manual editing · reviewed agent changes"}</span></div></div>
  </div>;
}
