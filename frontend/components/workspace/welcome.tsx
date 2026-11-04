"use client";
import { Code2, FolderOpen, FolderPlus, FilePlus2, GitBranch, ArrowUpRight, Square } from "lucide-react";
import type { RecentProject } from "@/types";

export function WorkspaceWelcome({ recent, onProject, onOpen, onFile, onEmpty, onClone, onRecent }: {recent: RecentProject[]; onProject: () => void; onOpen: () => void; onFile: () => void; onEmpty: () => void; onClone: () => void; onRecent: (id: string) => void}) {
  return <div className="workspace-welcome"><div className="welcome-brand"><Code2 size={30} /><span>FORGE WORKSPACE</span></div><h1>What do you<br />want to build?</h1><p>Your editor, terminal and engineering partner.<br />Start from an idea or continue where you left off.</p>
    <div className="workspace-start-actions">{[{label: "New project", detail: "An empty folder or a starter", icon: FolderPlus, action: onProject}, {label: "Open folder", detail: "Continue with an existing codebase", icon: FolderOpen, action: onOpen}, {label: "New file", detail: "Start typing. Save when ready.", icon: FilePlus2, action: onFile}, {label: "Clone repository", detail: "Bring a Git repository into Forge", icon: GitBranch, action: onClone}].map(({label, detail, icon: Icon, action}) => <button key={label} onClick={action}><Icon size={19} /><div><strong>{label}</strong><span>{detail}</span></div><ArrowUpRight size={14} /></button>)}</div>
    <button className="empty-workspace-link" onClick={onEmpty}><Square size={12} />Open an empty workspace</button>
    {!!recent.length && <div className="welcome-recent"><span className="eyebrow">RECENT WORKSPACES</span>{recent.slice(0, 5).map(project => <button key={project.id} onClick={() => onRecent(project.id)}><FolderOpen size={14} /><strong>{project.name}</strong><span>{project.path.includes("imports") ? "Imported snapshot" : project.path.includes(".data") ? "Forge workspace" : project.path}</span><ArrowUpRight size={12} /></button>)}</div>}
  </div>;
}
