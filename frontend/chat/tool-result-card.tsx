"use client";
import { Check, ChevronRight, FileCode2, FileDiff, ListChecks, ShieldCheck, TestTube2, SearchCode, AlertCircle } from "lucide-react";
import type { ToolResult } from "@/types";

export function ToolResultCard({ result, onSource, onDiff }: { result: ToolResult; onSource: (path: string, line?: number) => void; onDiff: (id: string) => void }) {
  const data = result.data;
  const Icon = result.type === "context" ? SearchCode : result.type === "tests" ? TestTube2 : result.type === "security" ? ShieldCheck : result.type === "changes" || result.type === "changeset" ? FileDiff : ListChecks;
  const bad = ["failed", "blocked", "needs_review"].includes(result.status);
  const files = Array.isArray(data.files) ? data.files as { file?: string; path?: string; start_line?: number; additions?: number; deletions?: number }[] : [];
  return <details className={`tool-result-card ${bad ? "attention" : ""}`}><summary><Icon size={15} /><strong>{result.title}</strong><span className={`tool-status ${bad ? "bad" : ""}`}>{result.status.replaceAll("_", " ")}</span><ChevronRight size={12} /></summary><div className="tool-card-body">
    {files.map((file, i) => <button className="tool-file" key={i} onClick={() => result.type === "changeset" && typeof data.change_id === "string" ? onDiff(data.change_id) : onSource(file.file || file.path || "", file.start_line)}><FileCode2 size={12} /><span>{file.file || file.path}</span>{file.additions !== undefined && <small className="diff-numbers">+{file.additions} −{file.deletions}</small>}</button>)}
    {Array.isArray(data.steps) && <ol>{(data.steps as string[]).map(step => <li key={step}>{step}</li>)}</ol>}
    {typeof data.summary === "string" && <p>{data.summary}</p>}
    {typeof data.evidence === "string" && <span className="eyebrow">{data.evidence}</span>}
    {typeof data.exit_code === "number" && <p>Exit code: {data.exit_code}</p>}
    {typeof data.score === "number" && <p><strong>Score {data.score}/10</strong> · {data.approved ? "Approved by reviewer" : "Needs attention"}</p>}
    {["critical_issues", "issues", "findings", "warnings", "suggestions"].map(key => Array.isArray(data[key]) && (data[key] as unknown[]).length > 0 ? <div key={key}><span className="eyebrow">{key.replaceAll("_", " ")}</span><ul>{(data[key] as unknown[]).map((item, i) => <li key={i}>{typeof item === "string" ? item : JSON.stringify(item)}</li>)}</ul></div> : null)}
    {data.bandit && typeof data.bandit === "object" ? <p><ShieldCheck size={12} />Bandit: {String((data.bandit as Record<string, unknown>).status)} · {Array.isArray((data.bandit as Record<string, unknown>).findings) ? ((data.bandit as Record<string, unknown>).findings as unknown[]).length : 0} findings in inspected scope</p> : null}
    {Array.isArray(data.command) && data.command.length > 0 && <code>{data.command.join(" ")}</code>}
    {typeof data.stdout === "string" && data.stdout && <pre>{data.stdout}</pre>}{typeof data.stderr === "string" && data.stderr && <pre>{data.stderr}</pre>}
    {typeof data.output === "string" && data.output && <pre>{data.output}</pre>}
    {result.type === "changeset" && typeof data.change_id === "string" && <button className="secondary-button" onClick={() => onDiff(data.change_id as string)}><FileDiff size={13} />Review Diff · Save Changes</button>}
    {bad && <p className="card-caution"><AlertCircle size={12} />This gate did not pass. Original source files remain unchanged.</p>}
  </div></details>;
}
