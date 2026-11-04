"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, FolderOpen, Folder, LoaderCircle, ShieldCheck, X } from "lucide-react";
import { BrowserDirectoryProvider, LocalPathProvider, type ProjectSource } from "@/services/project-source";
import { errorMessage } from "@/services/storage";
import type { RecentProject } from "@/types";

export function ProjectOpenDialog({ open, recent, opening, onClose, onOpen, onRecent }: { open: boolean; recent: RecentProject[]; opening: boolean; onClose: () => void; onOpen: (source: ProjectSource) => Promise<unknown>; onRecent: (id: string) => Promise<unknown> }) {
  const dialog = useRef<HTMLDialogElement>(null), input = useRef<HTMLInputElement>(null);
  const resolvePicker = useRef<((files: File[] | null) => void) | null>(null);
  const [path, setPath] = useState(""), [error, setError] = useState(""), [selecting, setSelecting] = useState(false);
  const [manual, setManual] = useState(false);
  useEffect(() => { if (open) { setError(""); dialog.current?.showModal(); } else dialog.current?.close(); }, [open]);
  useEffect(() => {
    const element = input.current;
    const cancelled = () => { resolvePicker.current?.(null); resolvePicker.current = null; };
    element?.addEventListener("cancel", cancelled);
    return () => { element?.removeEventListener("cancel", cancelled); cancelled(); };
  }, []);
  const fallback = () => new Promise<File[] | null>(resolve => { resolvePicker.current = resolve; input.current?.click(); });
  const browse = async (alternate = false) => {
    setError(""); setSelecting(true);
    try { const source = await new BrowserDirectoryProvider(fallback, alternate).select(); if (source) { await onOpen(source); onClose(); } }
    catch (e) { setError(errorMessage(e)); } finally { setSelecting(false); }
  };
  const local = async (raw: string) => {
    setError("");
    try { await onOpen(await new LocalPathProvider(raw).select()); onClose(); }
    catch (e) { setError(errorMessage(e)); }
  };
  const busy = opening || selecting;
  return <dialog ref={dialog} className="project-dialog" onCancel={e => { if (busy) e.preventDefault(); else onClose(); }} onClose={onClose}>
    <div className="dialog-header"><div className="dialog-icon"><FolderOpen size={23} /></div><button className="icon-button" aria-label="Close project dialog" onClick={onClose} disabled={busy}><X size={17} /></button></div>
    <span className="eyebrow">YOUR CODEBASE, IN CONTEXT</span><h2>Open a project</h2><p>Choose a folder. Forge will inspect the source and help you move from understanding to a reviewed change.</p>
    <button className="browse-primary" disabled={busy} onClick={() => browse()}>{busy ? <LoaderCircle size={19} className="spin" /> : <FolderOpen size={20} />}<div><strong>{opening ? "Indexing source…" : selecting ? "Reading selected folder…" : "Browse folder"}</strong><span>Choose a folder on this computer</span></div><ArrowRight size={17} /></button>
    <p className="permission-note"><ShieldCheck size={13} />Read permission only. Browser selection imports a source snapshot; the original folder stays untouched.</p>
    <button className="text-button alternate-picker" disabled={busy} onClick={() => browse(true)}>Use alternate folder picker</button>
    <input ref={input} type="file" multiple hidden {...({ webkitdirectory: "" } as Record<string, string>)} onChange={e => { resolvePicker.current?.(Array.from(e.target.files || [])); resolvePicker.current = null; e.target.value = ""; }} aria-label="Select project folder" />
    {error && <div className="inline-error" role="alert">{error}<button className="text-button" disabled={busy} onClick={() => browse(true)}>Try alternate folder picker</button></div>}
    <div className="dialog-divider"><span />or<span /></div><button className="manual-toggle" onClick={() => setManual(!manual)} aria-expanded={manual}>Enter path manually <span>{manual ? "−" : "+"}</span></button>
    {manual && <form onSubmit={e => { e.preventDefault(); void local(path); }}><label htmlFor="project-path">Absolute project path</label><div className="path-form"><input id="project-path" value={path} onChange={e => setPath(e.target.value)} placeholder="Paste an allowed project folder path" disabled={busy} /><button className="primary-button" disabled={busy || !path.trim()}>Open<ArrowRight size={14} /></button></div><span className="input-help">Direct folder access is limited to WORKSPACE_ROOTS. File writes always require an approved ChangeSet.</span></form>}
    {!!recent.length && <div className="recent-projects"><span className="eyebrow">RECENT PROJECTS</span>{recent.slice(0, 5).map(p => <button key={p.id} disabled={busy} onClick={async () => { try { await onRecent(p.id); onClose(); } catch (e) { setError(errorMessage(e)); } }}><Folder size={15} /><div><strong>{p.name}</strong><span>{p.path.includes("imports") ? "Browser source snapshot" : p.path}</span></div><ArrowRight size={13} /></button>)}</div>}
  </dialog>;
}
