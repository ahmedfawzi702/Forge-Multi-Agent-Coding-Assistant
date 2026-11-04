"use client";
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, FileCode2, FileText, Folder, Search, X } from "lucide-react";
import type { FileEntry } from "@/types";

export type ExplorerAction = "file" | "folder" | "rename" | "move" | "delete" | "copy" | "relative" | "open" | "refresh";
type TreeNode = {name: string; path: string; file?: FileEntry; children: TreeNode[]};
function createTree(files: FileEntry[], directories: string[]) {
  const root: TreeNode = {name: "", path: "", children: []};
  for (const entry of [...directories.map(path => ({path, file: undefined})), ...files.map(file => ({path: file.path, file}))]) {
    const parts = entry.path.split("/"); let parent = root;
    parts.forEach((name, index) => { const path = parts.slice(0, index + 1).join("/"); let node = parent.children.find(child => child.name === name); if (!node) { node = {name, path, children: []}; parent.children.push(node); } if (index === parts.length - 1 && entry.file) node.file = entry.file; parent = node; });
  }
  const sort = (nodes: TreeNode[]): TreeNode[] => nodes.sort((a, b) => Number(!!a.file) - Number(!!b.file) || a.name.localeCompare(b.name)).map(node => ({...node, children: sort(node.children)}));
  return sort(root.children);
}
function Row({ node, depth, active, search, onOpen, onMenu, onAction, reveal }: {node: TreeNode; depth: number; active?: string; search: boolean; onOpen: (path: string) => void; onMenu: (node: TreeNode, x: number, y: number) => void; onAction?: (action: ExplorerAction, path: string, directory: boolean) => void; reveal: string}) {
  const [expanded, setExpanded] = useState(depth === 0), open = expanded || search || reveal === node.path || reveal.startsWith(node.path + "/");
  return <div><button className={`tree-row ${node.file ? "" : "directory"} ${active === node.path ? "selected" : ""}`} style={{paddingLeft: depth * 14 + 12}} title={node.path} aria-expanded={node.file ? undefined : open} onClick={() => node.file ? onOpen(node.path) : setExpanded(!expanded)} onContextMenu={e => { e.preventDefault(); onMenu(node, e.clientX, e.clientY); }} onKeyDown={e => { if (e.key === "F2" || e.key === "Delete") {e.preventDefault(); onAction?.(e.key === "F2" ? "rename" : "delete", node.path, !node.file);} else if (e.key === "ContextMenu" || e.key === "F10" && e.shiftKey) { e.preventDefault(); const rect = e.currentTarget.getBoundingClientRect(); onMenu(node, rect.left + 30, rect.bottom); } else if (!node.file && ["ArrowRight", "ArrowLeft"].includes(e.key)) { e.preventDefault(); setExpanded(e.key === "ArrowRight"); } }}>
    {!node.file && (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}{node.file ? node.file.language === "markdown" ? <FileText size={14} /> : <FileCode2 size={14} className={`file-icon ${node.file.language}`} /> : <Folder size={14} />}<span>{node.name}</span>
  </button>{!node.file && open && node.children.map(child => <Row key={child.path} node={child} depth={depth + 1} active={active} search={search} onOpen={onOpen} onMenu={onMenu} onAction={onAction} reveal={reveal} />)}</div>;
}
export function FileTree({files, directories = [], selected, onOpen, onAction}: {files: FileEntry[]; directories?: string[]; selected?: string; onOpen: (path: string) => void; onAction?: (action: ExplorerAction, path: string, directory: boolean) => void}) {
  const [reveal, setReveal] = useState(""); const [search, setSearch] = useState(""), [menu, setMenu] = useState<{node: TreeNode; x: number; y: number} | null>(null);
  const filtered = useMemo(() => files.filter(f => f.path.toLowerCase().includes(search.toLowerCase())), [files, search]);
  const tree = useMemo(() => createTree(filtered, search ? [] : directories), [filtered, directories, search]);
  useEffect(() => { const close = () => setMenu(null); window.addEventListener("click", close); window.addEventListener("blur", close); return () => { window.removeEventListener("click", close); window.removeEventListener("blur", close); }; }, []);
  return <><label className="file-search"><Search size={13} /><input placeholder="Find a file…" aria-label="Find a file" value={search} onChange={e => setSearch(e.target.value)} />{search && <button onClick={() => setSearch("")} aria-label="Clear file search"><X size={12} /></button>}</label>
    <div className="tree-scroll">{tree.map(node => <Row key={node.path} node={node} depth={0} active={selected} search={!!search} onOpen={onOpen} reveal={reveal} onAction={onAction} onMenu={(node, x, y) => setMenu({node, x: Math.min(x, window.innerWidth - 210), y: Math.min(y, window.innerHeight - 300)})} />)}{!tree.length && <p className="quiet-note">{search ? "No matching files." : "Empty workspace. Create a file or folder to begin."}</p>}</div>
    {menu && <div className="explorer-menu" role="menu" style={{left: menu.x, top: menu.y}} onKeyDown={e => { if (e.key === "Escape") setMenu(null); }}>{([["file", "New File"], ["folder", "New Folder"], ["open", menu.node.file ? "Open file" : "Open folder"], ["rename", "Rename"], ["move", "Move"], ["delete", "Delete…"], ["copy", "Copy Path"], ["relative", "Copy Relative Path"], ["refresh", "Refresh"]] as [ExplorerAction, string][]).map(([action, label]) => <button role="menuitem" key={action} onClick={() => { if (action === "open" && !menu.node.file) setReveal(menu.node.path); onAction?.(action, menu.node.path, !menu.node.file); setMenu(null); }}>{label}</button>)}</div>}
  </>;
}
