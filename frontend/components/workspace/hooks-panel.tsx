"use client";
import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { errorMessage } from "@/services/storage";
import type { Project } from "@/types";

type Hook = {name: string; event: string; argv: string[]; timeout?: number};
type Run = {id: string; hook: Hook; status: string; evidence: string; stdout?: string; stderr?: string};
export function HooksPanel({project}: {project: Project | null}) {
  const [config, setConfig] = useState(""), [runs, setRuns] = useState<Run[]>([]), [error, setError] = useState(""), [busy, setBusy] = useState(false), [editing, setEditing] = useState(false);
  const id = project?.id;
  const refresh = async () => {if (!id) return; const result = await api<{hooks: Hook[]; runs: Run[]}>(`/projects/${id}/hooks`); setConfig(JSON.stringify({hooks: result.hooks}, null, 2)); setRuns(result.runs);};
  useEffect(() => {let active = true; if (id) void api<{hooks: Hook[]; runs: Run[]}>(`/projects/${id}/hooks`).then(data => {if (active) {setConfig(JSON.stringify({hooks: data.hooks}, null, 2)); setRuns(data.runs);}}).catch(err => {if (active) setError(errorMessage(err));}); return () => {active = false;};}, [id]);
  const run = async (key: string) => {if (!id || !window.confirm("Run this configured hook locally? Project code can access this machine.")) return; setBusy(true); try {await api(`/projects/${id}/hooks/${key}/run`, {method: "POST", body: JSON.stringify({approved: true})}); await refresh(); setError("");} catch (err) {setError(errorMessage(err));} finally {setBusy(false);}};
  const save = async () => {if (!id) return; setBusy(true); try {await api(`/projects/${id}/hooks/config`, {method: "POST", body: JSON.stringify(JSON.parse(config))}); setEditing(false); await refresh(); setError("");} catch (err) {setError(errorMessage(err));} finally {setBusy(false);}};
  return <div className="hooks-panel"><div className="dock-toolbar"><span>Local hooks · .forge/hooks.json</span><button disabled={!id || busy} onClick={() => {void refresh().catch(err => setError(errorMessage(err)));}}>Refresh</button><button disabled={!id} onClick={() => setEditing(!editing)}>Configure hooks</button></div><p className="quiet-note">AfterFileEdit and AfterAgentTask queue approval here. Before/AfterToolExecution use the task&apos;s execution permissions in its staged workspace. BeforeCommit runs after explicit approval.</p>{error && <p className="inline-error" role="alert">{error}</p>}{editing && <div className="hook-config"><p>Each hook has name, event, argv (an argument array) and optional timeout in seconds.</p><textarea aria-label="Hook configuration JSON" rows={10} value={config} onChange={event => setConfig(event.target.value)} /><button className="primary-button" disabled={busy} onClick={save}>Save hook configuration</button></div>}{runs.map(runItem => <details className="hook-run" key={runItem.id}><summary>{runItem.hook.name} · {runItem.hook.event} · {runItem.status} · {runItem.evidence}</summary><code>{runItem.hook.argv.join(" ")}</code>{runItem.status === "awaiting_approval" && <button className="secondary-button" disabled={busy} onClick={() => run(runItem.id)}>Approve and run hook</button>}{runItem.stdout && <pre>{runItem.stdout}</pre>}{runItem.stderr && <pre>{runItem.stderr}</pre>}</details>)}{!runs.length && <p className="quiet-note">No hook executions recorded.</p>}</div>;
}
