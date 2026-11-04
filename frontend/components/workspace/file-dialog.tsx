"use client";
import { useEffect, useRef, useState } from "react";
import { FilePlus2, LoaderCircle, X } from "lucide-react";
import { errorMessage } from "@/services/storage";

export type FileOperation = {kind: "file" | "folder" | "rename" | "move" | "save"; path?: string; value?: string};
export function FileDialog({ action, projectName, onClose, onSubmit }: {action: FileOperation; projectName?: string; onClose: () => void; onSubmit: (value: string, workspaceName: string) => Promise<void>}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [value, setValue] = useState(action.value || ""), [workspace, setWorkspace] = useState("Scratch workspace");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const title = {file: "New file", folder: "New folder", rename: "Rename", move: "Move", save: "Save As"}[action.kind];
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className="ide-dialog small-dialog" onCancel={e => { if (busy) e.preventDefault(); else onClose(); }} onClose={onClose}>
    <div className="panel-title"><div><FilePlus2 size={16} /><strong>{title}</strong></div><button aria-label="Close file dialog" disabled={busy} onClick={onClose}><X size={15} /></button></div>
    <form onSubmit={async e => { e.preventDefault(); setBusy(true); setError(""); try { await onSubmit(value.trim(), workspace.trim()); onClose(); } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); } }}>
      <p>{projectName ? <>Workspace: <strong>{projectName}</strong></> : "Save to a new local Forge workspace."}</p>
      {!projectName && <label>Workspace name<input value={workspace} onChange={e => setWorkspace(e.target.value)} required disabled={busy} /></label>}
      <label>{action.kind === "folder" ? "Folder path" : "File path"}<input autoFocus aria-label="Workspace file path" placeholder={action.kind === "folder" ? "src/components" : "src/main.py"} value={value} onChange={e => setValue(e.target.value)} required disabled={busy} /></label>
      <span className="input-help">Paths are relative to the workspace. Parent folders are created as needed.</span>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={busy}>Cancel</button><button className="primary-button" disabled={busy || !value.trim()}>{busy && <LoaderCircle size={13} className="spin" />}{action.kind === "save" ? "Save file" : title}</button></div>
    </form>
  </dialog>;
}
