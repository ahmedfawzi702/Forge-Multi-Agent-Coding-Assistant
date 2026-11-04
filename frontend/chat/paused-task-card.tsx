"use client";
import { useEffect, useState } from "react";
import { PauseCircle } from "lucide-react";
import { api } from "@/services/api";
import type { ChatResult } from "@/types";

type Models = {automatic_fallback: boolean; models: {model: string; status: string; retry_at?: string | null}[]};

export function PausedTaskCard({result, busy, onResume, onCancel, onDiff}: {
  result: ChatResult; busy: boolean; onResume: (model?: string) => void;
  onCancel: () => void; onDiff: (id: string) => void;
}) {
  const [now, setNow] = useState(Date.now()), [models, setModels] = useState<Models | null>(null);
  const [switching, setSwitching] = useState(false), [model, setModel] = useState(""), [error, setError] = useState("");
  useEffect(() => {if (!result.retry_at) return; const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer);}, [result.retry_at]);
  const cooldown = result.retry_at ? Math.max(0, Math.ceil((Date.parse(result.retry_at) - now) / 1000)) : 0;
  const progress = result.staged_changes;
  const reasons: Record<string, string> = {PROVIDER_RATE_LIMIT: "Model provider temporarily rate-limited", TOOL_CALL_BUDGET: "Tool budget reached", MODEL_CALL_LIMIT: "Model call allowance reached", GLOBAL_AGENT_STEP_LIMIT: "Agent step limit reached", USER_PAUSED: "Paused by you"};
  const switchModel = async () => {
    setSwitching(true); setError("");
    try {setModels(await api<Models>("/models"));} catch {setError("Could not load configured models.");}
  };
  return <section className="paused-task-card" aria-label="Task checkpoint">
    <strong><PauseCircle size={16} /> Task paused safely</strong>
    <p>{reasons[result.pause_reason || ""] || (result.pause_reason || "Checkpoint saved").replaceAll("_", " ")}</p>
    <dl><div><dt>Stage</dt><dd>{(result.stage || "IMPLEMENT").toLowerCase()}</dd></div>
      <div><dt>Staged files</dt><dd>{progress?.files ?? 0}</dd></div>
      <div><dt>Staged directories</dt><dd>{progress?.directories ?? 0}</dd></div>
      <div><dt>Applied files</dt><dd>{progress?.applied_files ?? 0}</dd></div></dl>
    {!result.implementation_complete && <p>Implementation is incomplete. Final tests, security and review: NOT RUN.</p>}
    {cooldown > 0 && <p>Provider cooldown: {cooldown}s. Resume when available, or choose another configured model.</p>}
    <p>Automatic model fallback: {(models?.automatic_fallback ?? result.model_selection?.automatic_fallback) ? "ON" : "OFF"}</p>
    <div className="checkpoint-actions">
      <button className="secondary-button" disabled={busy || cooldown > 0} onClick={() => onResume()}>Resume</button>
      <button className="secondary-button" disabled={busy} onClick={() => void switchModel()}>Switch model</button>
      {result.change_id && <button className="secondary-button" onClick={() => onDiff(result.change_id!)}>Review staged changes</button>}
      <button className="secondary-button" disabled={busy} onClick={onCancel}>Cancel task</button>
    </div>
    {switching && <div><label>Configured model <select value={model} onChange={event => setModel(event.target.value)}><option value="">Choose a model</option>
      {models?.models.map(item => <option key={item.model} value={item.model} disabled={item.status === "rate_limited"}>{item.model}{item.status === "rate_limited" ? " · cooling down" : ""}</option>)}</select></label>
      {models && models.models.length < 2 && <p>Only one model is configured. Configure another compatible model in backend settings to switch.</p>}
      <button className="secondary-button" disabled={busy || !model} onClick={() => onResume(model)}>Continue with selected model</button>
    </div>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
