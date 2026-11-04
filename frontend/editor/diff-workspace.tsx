"use client";
import { useEffect, useRef, useState } from "react";
import { Check, FileDiff, LoaderCircle, ShieldAlert, X } from "lucide-react";
import { loadMonaco } from "@/editor/code-editor";
import { CodeDiff } from "@/editor/code-diff";
import { api } from "@/services/api";
import { errorMessage } from "@/services/storage";
import type { ChangeSet } from "@/types";

export function DiffWorkspace({ id, onClose, onApplied, onUpdated, onCurrent, onRegenerate }: { id: string; onClose: () => void; onApplied: () => void; onUpdated: (change: ChangeSet) => void; onCurrent: (path: string) => void; onRegenerate: (path: string) => void }) {
  const [change, setChange] = useState<ChangeSet | null>(null), [ready, setReady] = useState(false);
  const [selected, setSelected] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [highApproval, setHighApproval] = useState(false), [testApproval, setTestApproval] = useState(false);
  const currentId = useRef(id); currentId.current = id;
  useEffect(() => {
    let mounted = true; setChange(null); setSelected(0); setError(""); setHighApproval(false); setTestApproval(false); setBusy(false);
    void Promise.all([loadMonaco(), api<ChangeSet>(`/changes/${id}`)]).then(([, data]) => { if (mounted) { setReady(true); setChange(data); onUpdated(data); } }).catch(e => { if (mounted) setError(errorMessage(e)); });
    return () => { mounted = false; };
  }, [id]);
  const action = async (type: "apply" | "reject" | "validate", files?: string[]) => {
    setBusy(true); setError("");
    try {
      const result = await api<ChangeSet>(`/changes/${id}/${type}`, { method: "POST", body: JSON.stringify({ files, approve_high_risk: highApproval, allow_execution: testApproval }) });
      onUpdated(result); if (type === "apply") onApplied();
      if (currentId.current === id) setChange(result);
    } catch (e) { if (currentId.current === id) setError(errorMessage(e)); } finally { if (currentId.current === id) setBusy(false); }
  };
  const file = change?.proposal.files[selected], needsHigh = change?.proposal.files.some(f => !f.applied && !f.rejected && ["HIGH", "CRITICAL"].includes(f.risk));
  const applicable = change?.can_apply && ["proposed", "partially_applied"].includes(change.status) && (!needsHigh || highApproval);
  return <div className="diff-workspace"><div className="panel-title"><div><FileDiff size={14} /><strong>Review changes</strong><span className="version-chip">{change?.status || "LOADING"}</span></div><button className="icon-button" onClick={onClose} aria-label="Close diff"><X size={15} /></button></div>
    {change && <><div className="diff-summary"><p>{change.proposal.summary}</p><div className="verification-badges">{["static", "security", "tests"].map(key => <span key={key} data-state={String(change.proposal[key as "static" | "security" | "tests"].status)}>{key}: {String(change.proposal[key as "static" | "security" | "tests"].status || "not_run")}</span>)}<span>review: {String(change.proposal.review.status || (typeof change.proposal.review.approved === "boolean" ? change.proposal.review.approved ? "approved" : "not_approved" : "not_run"))}</span></div></div><div className="editor-tabs">{change.proposal.files.map((f, i) => <button key={f.path} className={`editor-tab ${selected === i ? "active" : ""}`} onClick={() => setSelected(i)}>{f.applied ? <Check size={12} /> : <FileDiff size={12} />}{f.path.split("/").at(-1)}<span className="diff-numbers">+{f.additions} −{f.deletions}</span></button>)}</div></>}
    {error && <div className="inline-error" role="alert">{error}</div>}
    {error && /changed|stale|created manually|already exists/i.test(error) && file && <div className="diff-conflict-actions"><p>Your current files were kept. Review the current source or regenerate the proposal against its latest version.</p><button className="secondary-button" onClick={() => onCurrent(file.path)}>Review current file</button><button className="secondary-button" disabled={busy} onClick={() => action("reject", [file.path])}>Keep manual changes</button><button className="secondary-button" onClick={() => onRegenerate(file.path)}>Regenerate patch</button><button className="text-button" onClick={onClose}>Cancel</button></div>}
    <div className="diff-column-labels"><span>Original snapshot</span><span>Proposed changes · requires Save</span></div>
    <div className="diff-editor-area">{ready && file ? <CodeDiff before={file.before} after={file.after} path={file.path} /> : !error && <div className="editor-loading"><LoaderCircle size={17} className="spin" />Loading diff…</div>}</div>
    {change && <div className="diff-actions"><p>{file?.reason}</p>{needsHigh && <label className="approval-option"><input type="checkbox" checked={highApproval} onChange={e => setHighApproval(e.target.checked)} /><ShieldAlert size={13} />I explicitly approve the high-risk source edits.</label>}
      {!change.can_apply && change.proposal.tests.status === "awaiting_approval" && <div className="test-permission"><label className="approval-option"><input type="checkbox" checked={testApproval} onChange={e => setTestApproval(e.target.checked)} />Allow pytest to execute this snapshot locally.</label><p>Project tests can access your machine. This runner is not an OS sandbox.</p><button className="secondary-button" disabled={busy || !testApproval} onClick={() => action("validate")}>Run local tests</button></div>}
      {file?.rejected && <p className="quiet-note">This file was rejected and will not be applied.</p>}
      <div><button className="text-button" disabled={busy || !["proposed", "partially_applied"].includes(change.status)} onClick={() => action("reject")}>Discard remaining changes</button><button className="text-button" disabled={busy || !!file?.applied || !!file?.rejected || !["proposed", "partially_applied"].includes(change.status)} onClick={() => action("reject", file ? [file.path] : [])}>Reject this file</button><span /><button className="secondary-button" disabled={busy || !applicable || file?.applied || file?.rejected} onClick={() => action("apply", file ? [file.path] : [])}>Save this file</button><button className="primary-button" disabled={busy || !applicable} onClick={() => action("apply")}>{busy ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />}Save All Changes</button></div>
      <small>{change.proposal.source_kind === "browser" ? "Changes apply to the imported snapshot. Your original selected folder is untouched." : "Pending approval. Save writes the approved files to disk; Git commit and push are separate actions."}</small>
    </div>}
  </div>;
}
