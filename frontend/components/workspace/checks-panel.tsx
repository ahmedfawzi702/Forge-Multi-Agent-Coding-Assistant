"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, LoaderCircle, Square, TerminalSquare } from "lucide-react";
import { api } from "@/services/api";
import { errorMessage } from "@/services/storage";
import { ToolResultCard } from "@/chat/tool-result-card";
import type { Project, ToolResult } from "@/types";

export type CommandEvidence = {argv: string[]; stdout: string; stderr: string; exit_code: number; timed_out: boolean};
export function ChecksPanel({project, request, tools, onEvidence, onSource, onDiff}: {project: Project | null; request?: {argv: string[]; token: number; projectId: string}; tools: ToolResult[]; onEvidence: (result: CommandEvidence) => void; onSource: (path: string, line?: number) => void; onDiff: (id: string) => void}) {
  const [result, setResult] = useState<CommandEvidence | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null), locked = useRef(false), callback = useRef(onEvidence); callback.current = onEvidence;
  const id = project?.id;
  const run = useCallback(async (argv: string[]) => {if (!id || locked.current) return; locked.current = true; const controller = new AbortController(); abort.current = controller; setBusy(true); setError(""); try {const response = await fetch(`/api/projects/${id}/commands`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({argv, timeout: 120, approved: true}), signal: controller.signal}); const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Command failed"); if (!controller.signal.aborted) {setResult(data); callback.current(data);}} catch (err) {setError(controller.signal.aborted ? "Command stopped." : errorMessage(err));} finally {setBusy(false); locked.current = false; abort.current = null;}}, [id]);
  useEffect(() => {if (request && request.projectId === id) void run(request.argv);}, [request?.token, run]);
  useEffect(() => () => abort.current?.abort(), [id]);
  const python = project?.project_map.language.includes("python");
  return <div className="checks-panel"><div className="dock-toolbar"><button className="secondary-button" disabled={!project || busy} onClick={() => run(python ? ["python", "-m", "pytest", "-q"] : ["npm", "test"])}>Run tests</button><button disabled={!project || busy} onClick={() => run(python ? ["ruff", "check", "--isolated", "."] : ["npm", "run", "lint"])}>Run lint</button><button disabled={!project || busy} onClick={() => run(python ? ["mypy", "."] : ["npm", "run", "typecheck"])}>Check types</button>{project?.project_map.files.some(f => f.path === "package.json") && <button disabled={busy} onClick={() => run(["npm", "run", "build"])}>Build</button>}{busy && <><LoaderCircle size={13} className="spin" /><span>Running…</span><button aria-label="Stop command" onClick={() => abort.current?.abort()}><Square size={12} /></button></>}</div>
    {error && <div className="inline-error" role="alert">{error}</div>}
    {result ? <div className="command-evidence"><div><TerminalSquare size={13} /><code>{result.argv.join(" ")}</code><span className={result.exit_code === 0 ? "success-text" : "failure-text"}>{result.timed_out ? "Timed out" : `Exit ${result.exit_code}`}</span>{result.exit_code === 0 && <Check size={13} />}</div><pre>{result.stdout}{result.stderr}</pre><span className="eyebrow">VERIFIED COMMAND OUTPUT · LOCAL WORKSPACE</span></div> : <p className="quiet-note">Run the project's tests or checks. Results are shown only after actual execution.</p>}
    <div className="dock-tool-cards">{tools.filter(tool => ["tests", "static", "security", "review"].includes(tool.type)).map((tool, i) => <ToolResultCard key={i} result={tool} onSource={onSource} onDiff={onDiff} />)}</div>
  </div>;
}
