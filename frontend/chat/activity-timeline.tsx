"use client";
import { Check, ChevronDown, LoaderCircle, PauseCircle, X, Terminal } from "lucide-react";
import type { AgentEvent } from "@/types";

export function AgentActivityTimeline({ events, running = false }: { events: AgentEvent[]; running?: boolean }) {
  const statuses = events.filter(e => ["agent_status", "task_started", "task_restarted", "file_inspected", "tool_started", "tool_completed", "tool_blocked", "command_completed", "error", "task_failed", "task_completed", "task_paused", "task_cancelled", "task_blocked"].includes(e.type));
  if (!statuses.length) return null;
  return <details className="execution-timeline" open={running || undefined}><summary><Terminal size={13} /><span>{running ? statuses.at(-1)?.message || "Working…" : "Activity & verification"}</span><span className="timeline-count">{statuses.length} steps</span>{running ? <LoaderCircle size={13} className="spin" /> : <ChevronDown size={12} />}</summary><div>{statuses.map((event, i) => <div className={`timeline-step ${event.type === "error" || event.type === "task_failed" ? "error" : ""}`} key={i}>{running && i === statuses.length - 1 ? <LoaderCircle size={12} className="spin" /> : event.type === "error" || event.type === "task_failed" || event.type === "task_cancelled" ? <X size={12} /> : event.type === "task_paused" || event.type === "task_blocked" ? <PauseCircle size={12} /> : <Check size={12} />}<span>{event.message}</span></div>)}</div></details>;
}
