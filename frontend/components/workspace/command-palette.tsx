"use client";
import { useEffect, useRef, useState } from "react";
import { Search, FileCode2, Hash, Command } from "lucide-react";
import type { Project } from "@/types";

export type PaletteCommand = {label: string; shortcut?: string; run: () => void};
export function CommandPalette({ mode, files, project, commands, onOpen, onClose }: {mode: "command" | "file" | "symbol"; files: string[]; project: Project | null; commands: PaletteCommand[]; onOpen: (path: string, line?: number) => void; onClose: () => void}) {
  const ref = useRef<HTMLDialogElement>(null), [query, setQuery] = useState(""), [selected, setSelected] = useState(0);
  useEffect(() => { ref.current?.showModal(); }, []);
  const rows = (mode === "command" ? commands : mode === "file" ? files.map(path => ({label: path, run: () => onOpen(path), shortcut: undefined})) : (project?.project_map.symbols || []).map(symbol => ({label: `${symbol.name} · ${symbol.file_path}:${symbol.start_line}`, run: () => onOpen(symbol.file_path, symbol.start_line), shortcut: undefined}))).filter(item => item.label.toLowerCase().includes(query.toLowerCase())).slice(0, 100);
  const invoke = (row: PaletteCommand) => { onClose(); row.run(); };
  return <dialog ref={ref} className="command-palette" onCancel={onClose} onClose={onClose}>
    <label><Search size={17} /><input autoFocus aria-label={mode === "file" ? "Quick open" : mode === "symbol" ? "Search symbols" : "Command palette"} placeholder={mode === "command" ? "Type a command…" : mode === "file" ? "Search files by name…" : "Search workspace symbols…"} value={query} onChange={e => { setQuery(e.target.value); setSelected(0); }} onKeyDown={e => { if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); setSelected(n => Math.max(0, Math.min(rows.length - 1, n + (e.key === "ArrowDown" ? 1 : -1)))); } else if (e.key === "Enter" && rows[selected]) { e.preventDefault(); invoke(rows[selected]); } }} /><kbd>esc</kbd></label>
    <div className="palette-results" role="listbox">{rows.map((row, index) => <button key={row.label} role="option" aria-selected={index === selected} className={index === selected ? "selected" : ""} onMouseEnter={() => setSelected(index)} onClick={() => invoke(row)}>{mode === "file" ? <FileCode2 size={14} /> : mode === "symbol" ? <Hash size={14} /> : <Command size={14} />}<span>{row.label}</span>{row.shortcut && <kbd>{row.shortcut}</kbd>}</button>)}{!rows.length && <p>No matching {mode === "file" ? "files" : mode === "symbol" ? "symbols" : "commands"}.</p>}</div>
    <footer>↑ ↓ to navigate <span>↵ to open</span></footer>
  </dialog>;
}
