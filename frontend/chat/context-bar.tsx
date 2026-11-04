"use client";
import { FileCode2, Plus, X } from "lucide-react";
import { useState } from "react";
import type { Project, SelectionContext } from "@/types";

export function ContextBar({ project, attached, selection, onRemove, onRemoveSelection, onAttach }: { project: Project | null; attached: string[]; selection: SelectionContext | null; onRemove: (path: string) => void; onRemoveSelection: () => void; onAttach: (path: string) => void }) {
  const [menu, setMenu] = useState(false), [search, setSearch] = useState("");
  return <div className="context-bar"><span className="context-auto">Auto context</span>{attached.map(path => <span className="context-chip" key={path} title={path}><FileCode2 size={11} /><span>{path.split("/").at(-1)}</span><button onClick={() => onRemove(path)} aria-label={`Remove context ${path}`}><X size={10} /></button></span>)}
    {selection && <span className="context-chip selection-chip">Lines {selection.start_line}–{selection.end_line}<button onClick={onRemoveSelection} aria-label="Remove selected lines"><X size={10} /></button></span>}
    <button className="context-add" aria-label="Attach context file" disabled={!project || attached.length >= 8} onClick={() => setMenu(!menu)}><Plus size={12} /></button>
    {menu && <div className="context-menu"><input autoFocus aria-label="Search context files" placeholder="Find a file to attach…" value={search} onChange={e => setSearch(e.target.value)} /><div>{project?.project_map.files.filter(f => !attached.includes(f.path) && f.path.toLowerCase().includes(search.toLowerCase())).slice(0, 80).map(file => <button key={file.path} onClick={() => { onAttach(file.path); setMenu(false); setSearch(""); }}><FileCode2 size={12} />{file.path}</button>)}</div><button className="text-button" onClick={() => setMenu(false)}>Close</button></div>}
  </div>;
}
