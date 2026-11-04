"use client";
import { useEffect, useRef, useState } from "react";
import { FolderPlus, GitBranch, LoaderCircle, X } from "lucide-react";
import { api } from "@/services/api";
import { errorMessage } from "@/services/storage";

export function NewProjectDialog({ clone, onClose, onCreate }: {clone?: boolean; onClose: () => void; onCreate: (body: {name: string; location?: string; template: string; url?: string; branch?: string}) => Promise<unknown>}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(""), [template, setTemplate] = useState("empty"), [location, setLocation] = useState("");
  const [roots, setRoots] = useState<string[]>([]), [url, setUrl] = useState(""), [branch, setBranch] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { dialog.current?.showModal(); void api<{roots: string[]}>("/workspace/options").then(value => setRoots(value.roots)).catch(() => {}); }, []);
  return <dialog ref={dialog} className="ide-dialog" onCancel={e => { if (busy) e.preventDefault(); else onClose(); }} onClose={onClose}>
    <div className="panel-title"><div>{clone ? <GitBranch size={17} /> : <FolderPlus size={17} />}<strong>{clone ? "Clone repository" : "Create project"}</strong></div><button aria-label="Close new project dialog" disabled={busy} onClick={onClose}><X size={16} /></button></div>
    <form onSubmit={async e => { e.preventDefault(); setBusy(true); setError(""); try { await onCreate({name, template, location: location || undefined, url: clone ? url : undefined, branch: clone ? branch : undefined}); onClose(); } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); } }}>
      <p>{clone ? "Clone an HTTPS repository into a new workspace." : "Start with an empty folder or a small, editable starter."}</p>
      {clone && <label>Repository URL<input autoFocus value={url} onChange={e => { setUrl(e.target.value); if (!name) setName(e.target.value.split("/").at(-1)?.replace(/\.git$/, "") || ""); }} placeholder="https://github.com/owner/repository.git" required disabled={busy} /></label>}
      {clone && <label>Branch (optional)<input value={branch} onChange={e => setBranch(e.target.value)} placeholder="Default branch" disabled={busy} /></label>}<label>Project name<input autoFocus={!clone} value={name} onChange={e => setName(e.target.value)} placeholder="my-app" required disabled={busy} /></label>
      <label>Location<select value={location} onChange={e => setLocation(e.target.value)} disabled={busy}><option value="">Forge workspaces</option>{roots.map(root => <option key={root} value={root}>{root}</option>)}</select></label>
      <span className="input-help">A new folder is created at this location. Existing folders are never replaced.</span>
      {!clone && <label>Template<select value={template} onChange={e => setTemplate(e.target.value)} disabled={busy}>{[["empty", "Empty project"], ["python", "Python"], ["fastapi", "FastAPI"], ["node", "Node.js"], ["next", "Next.js"], ["react", "React"]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
      <p className="input-help">{template === "empty" && !clone ? "Empty means empty: only the workspace folder is created." : "Dependencies are not installed automatically. Use the integrated terminal when you are ready."}</p>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <div className="dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={onClose}>Cancel</button><button className="primary-button" disabled={busy || !name.trim()}>{busy && <LoaderCircle size={14} className="spin" />}{busy ? clone ? "Cloning…" : "Creating…" : clone ? "Clone repository" : "Create project"}</button></div>
    </form>
  </dialog>;
}
