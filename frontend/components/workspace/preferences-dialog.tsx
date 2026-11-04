"use client";
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { api } from "@/services/api";
import { errorMessage } from "@/services/storage";

type Decision = "allow" | "ask" | "deny";
type Preferences = {instructions: string; explanation_level: string | null; capabilities: Record<string, Decision>};
const defaults: Record<string, Decision> = {"filesystem.read": "allow", "filesystem.write": "allow", "terminal.execute": "ask", "git.read": "allow", "git.write": "ask", network: "ask", "package.install": "ask", subagent: "allow"};
export function PreferencesDialog({projectId, onClose}: {projectId?: string; onClose: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {dialog.current?.showModal();}, []);
  const [scope, setScope] = useState(projectId ? "project" : "global"), [value, setValue] = useState<Preferences | null>(null);
  const [effective, setEffective] = useState<Record<string, Decision>>(defaults), [rules, setRules] = useState<{file: string; content: string}[]>([]);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [saved, setSaved] = useState(false);
  const endpoint = scope === "project" ? `/projects/${projectId}/preferences` : "/preferences";
  useEffect(() => {let current = true; setValue(null); setError(""); setSaved(false); void api<Preferences | {local: Preferences; effective: Preferences; rules: {file: string; content: string}[]}>(endpoint).then(result => {if (!current) return; if ("local" in result) {setValue(result.local); setEffective(result.effective.capabilities); setRules(result.rules);} else {setValue(result); setEffective(defaults); setRules([]);}}).catch(err => {if (current) setError(errorMessage(err));}); return () => {current = false;};}, [endpoint]);
  const save = async () => {if (!value) return; setBusy(true); try {await api(endpoint, {method: "POST", body: JSON.stringify(value)}); setSaved(true); setError("");} catch (err) {setError(errorMessage(err));} finally {setBusy(false);}};
  return <dialog ref={dialog} className="ide-dialog preferences-dialog" aria-label="Agent settings" onCancel={onClose}><header><h2>Agent settings</h2><button className="icon-button" aria-label="Close settings" onClick={onClose}><X size={16} /></button></header><label>Scope<select value={scope} onChange={e => setScope(e.target.value)}><option value="global">Global defaults</option>{projectId && <option value="project">This project</option>}</select></label>
    {value && <><label>Instructions<textarea rows={5} maxLength={8000} value={value.instructions} placeholder="Coding style, architecture constraints and preferences…" onChange={e => {setValue({...value, instructions: e.target.value}); setSaved(false);}} /></label><label>Explanation detail<select value={value.explanation_level || ""} onChange={e => setValue({...value, explanation_level: e.target.value || null})}><option value="">Inherit default</option>{["beginner", "intermediate", "advanced"].map(level => <option key={level}>{level}</option>)}</select></label><p className="quiet-note">Agent permissions apply to AI tools. Ask and Plan always prohibit edits and execution. Manual editor saves and your terminal remain independent.</p><div className="capability-grid">{Object.keys(defaults).map(capability => <label key={capability}><code>{capability}</code><select aria-label={capability} value={value.capabilities[capability] || ""} onChange={e => {const next = {...value.capabilities}; if (e.target.value) next[capability] = e.target.value as Decision; else delete next[capability]; setValue({...value, capabilities: next}); setSaved(false);}}><option value="">Inherit ({effective[capability] || defaults[capability]})</option><option value="allow">Allow</option><option value="ask">Ask</option><option value="deny">Deny</option></select></label>)}</div>{rules.length > 0 && <details><summary>{rules.length} project rule files loaded</summary>{rules.map(rule => <details key={rule.file}><summary>{rule.file}</summary><pre>{rule.content}</pre></details>)}</details>}<footer><span role="status">{saved ? "Saved" : "Changes apply to new runs"}</span><button className="primary-button" disabled={busy} onClick={save}>Save settings</button></footer></>}{error && <p className="inline-error" role="alert">{error}</p>}
  </dialog>;
}
