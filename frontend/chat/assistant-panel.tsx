"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Code2, FileCode2, FolderOpen, History, Layers3, MessageSquare, Plus, ShieldCheck, Sparkles, Wrench } from "lucide-react";
import { ChatComposer } from "@/chat/chat-composer";
import { MessageRenderer } from "@/chat/message-renderer";
import { AgentActivityTimeline } from "@/chat/activity-timeline";
import { ToolResultCard } from "@/chat/tool-result-card";
import { PlanActions } from "@/chat/plan-actions";
import { PausedTaskCard } from "@/chat/paused-task-card";
import type { useChat } from "@/hooks/use-chat";
import type { ChangeSet, ChatMode, Health, Project, SelectionContext, ToolResult } from "@/types";

function changeSummary(change: ChangeSet) {
  const p = change.proposal;
  const state = change.status === "restored" ? "Agent changes were restored from a checkpoint. Later saved edits were protected by conflict checks."
    : change.status === "applied" ? `Changes applied to the ${p.source_kind === "browser" ? "imported snapshot" : "local project"}.`
    : change.status === "partially_applied" ? "Selected files applied. Remaining changes are available in the diff."
    : change.status === "rejected" ? "ChangeSet rejected. No proposed files were applied."
    : change.can_apply ? "Validation passed. Review the diff and choose Apply changes."
    : "Application is blocked until all required validation gates pass.";
  const review = String(p.review.status || (typeof p.review.approved === "boolean" ? p.review.approved ? "approved" : "not_approved" : "not_run")).replaceAll("_", " ");
  const score = typeof p.review.score === "number" ? ` (${p.review.score}/10)` : "";
  return `${p.summary}\n\n### ${change.status === "applied" ? "Applied" : "Proposed/staged"} files\n${p.files.filter(f => !f.directory).map(f => `- \`${f.path}\` (+${f.additions} / −${f.deletions}): ${f.reason}`).join("\n")}\n\n**Tests:** ${String(p.tests.status || "not_run").replaceAll("_", " ")}. **Security:** ${p.security.status || "not_run"}. **Review:** ${review}${score}.\n\n${state}${p.source_kind === "browser" ? " The original selected folder remains read only." : ""}`;
}

export function AssistantPanel({ project, health, chat, attached, selected, onSend, onRemove, onRemoveSelection, onAttach, onSource, onDiff, onBrowse }: {
  project: Project | null; health: Health | null; chat: ReturnType<typeof useChat>; attached: string[]; selected: SelectionContext | null;
  onSend: (text: string, mode?: ChatMode, level?: string, allowTests?: boolean) => void;
  onRemove: (path: string) => void; onRemoveSelection: () => void; onAttach: (path: string) => void;
  onSource: (path: string, line?: number) => void; onDiff: (id: string) => void; onBrowse: () => void;
}) {
  const [history, setHistory] = useState(false), [elapsed, setElapsed] = useState(0);
  const scroll = useRef<HTMLDivElement>(null), follow = useRef(true);
  const paths = project?.project_map.files.map(f => f.path) || [];
  useEffect(() => { if (scroll.current) { if (!chat.messages.length) scroll.current.scrollTop = 0; else if (follow.current) scroll.current.scrollTop = scroll.current.scrollHeight; } }, [chat.messages, chat.events]);
  useEffect(() => { if (!chat.busy) return; setElapsed(0); const started = Date.now(); const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000); return () => clearInterval(timer); }, [chat.busy]);
  return <div className="assistant-panel"><div className="panel-title assistant-title"><div><span className="assistant-header-symbol"><Code2 size={14} /></span><strong>Forge</strong><span className="assistant-subtitle">Your engineering partner</span></div><div>{chat.busy && <span className="elapsed-time">Working · {elapsed}s</span>}<button className="icon-button" aria-label="Conversation history" onClick={() => setHistory(!history)}><History size={15} /></button><button className="new-chat-button" disabled={chat.busy} onClick={chat.newChat} aria-label="New conversation"><Plus size={14} /><span>New chat</span></button></div></div>
    {history && <div className="history-menu"><div className="eyebrow">CONVERSATIONS</div>{chat.conversations.length ? chat.conversations.map(c => <button key={c.id} disabled={chat.busy} onClick={() => { void chat.history(c.id); setHistory(false); }}><MessageSquare size={13} /><span>{c.title}</span></button>) : <p>No conversations yet.</p>}</div>}
    <div className="conversation-scroll" ref={scroll} onScroll={e => { const el = e.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 130; }}>
      {!chat.messages.length && <div className="assistant-welcome"><div className="welcome-topline"><span className="assistant-mark"><Code2 size={27} /></span><span className="eyebrow">CONTEXT FIRST. CONFIDENT NEXT STEPS.</span></div><h1>What are we<br /><span>working on?</span></h1><p>{project ? <>I have the map of <strong>{project.name}</strong>. Ask a question, investigate a bug, or describe the change you want to make.</> : "Bring your codebase. Ask a question, trace a problem, or work toward your next change."}</p>
        {project ? <div className="welcome-prompts">{[{ icon: Layers3, title: "Understand this project", prompt: "Understand this project and explain its architecture, using source evidence.", detail: "Find the entry points and connections" }, { icon: Wrench, title: "Investigate a bug", prompt: "Help me investigate potential bugs in this project. Identify evidence and unknowns before proposing changes.", detail: "Start with evidence, then narrow the cause" }, { icon: FileCode2, title: "Review the code", prompt: "Review the selected file, or the main project components, for correctness and likely regressions.", detail: "Look for edge cases and regressions" }, { icon: ShieldCheck, title: "Check security", prompt: "Check the relevant project code for security issues and cite the inspected sources.", detail: "Inspect risks without changing files" }].map(({ icon: Icon, title, prompt, detail }) => <button key={title} onClick={() => { follow.current = true; onSend(prompt); }} disabled={!health}><Icon size={17} /><div><strong>{title}</strong><span>{detail}</span></div><ArrowRight size={13} /></button>)}</div> : <><button className="primary-button browse-welcome" onClick={onBrowse}><FolderOpen size={16} />Browse folder<ArrowRight size={15} /></button><div className="welcome-principles"><span><FileCode2 size={13} />Answers tied to source</span><span><ShieldCheck size={13} />Changes by approval</span></div></>}
        <div className="welcome-note"><Sparkles size={13} />One conversation. The right tools for the task.</div></div>}
      {chat.messages.map((message, index) => {
        const running = chat.busy && index === chat.messages.length - 1;
        const latest = message.result?.change_id ? chat.changes[message.result.change_id] : null;
        const canResume = !!message.result?.resumable && (!latest || latest.status === "proposed" && !latest.can_apply && (!latest.proposal.run_id || latest.proposal.run_id === message.result.run_id));
        const tools = (message.result?.artifacts || (message.events || []).filter(event => event.data.type && event.data.title).map(event => event.data as unknown as ToolResult)).map(tool => {
          if (!latest) return tool;
          if (["static", "security", "tests", "review"].includes(tool.type)) {
            const report = latest.proposal[tool.type as "static" | "security" | "tests" | "review"];
            return { ...tool, status: typeof report.status === "string" ? report.status : tool.type === "review" && typeof report.approved === "boolean" ? report.approved ? "passed" : "not_approved" : "not_run", data: report };
          }
          return ["changes", "changeset"].includes(tool.type) ? { ...tool, status: latest.status, data: { ...tool.data, ready: latest.can_apply } } : tool;
        });
        return <article key={index} className={`conversation-message ${message.role}`}><div className="message-author">{message.role === "user" ? <span className="user-avatar">Y</span> : <span className="bot-avatar"><Code2 size={13} /></span>}<strong>{message.role === "user" ? "You" : "Forge"}</strong>{message.result && <span className="result-tag">{latest && !canResume ? latest.status.replaceAll("_", " ") : message.result.status === "completed" ? message.result.provider === "evidence" ? "Evidence report" : "Complete" : message.result.status.replaceAll("_", " ")}</span>}</div>
          {message.role === "assistant" && message.events && <AgentActivityTimeline events={message.events} running={running} />}
          {tools.length > 0 && <div className="inline-tool-results">{tools.map((tool, i) => <ToolResultCard key={i} result={tool} onSource={onSource} onDiff={onDiff} />)}</div>}
          {message.content && <MessageRenderer content={latest && !canResume ? changeSummary(latest) : message.content} paths={paths} onSource={onSource} />}
          {message.result?.intents.includes("PLAN") && message.result.status === "completed" && <PlanActions plan={message.content} disabled={chat.busy} onImplement={plan => onSend(`Implement the following agreed specification with tests:\n${plan}`, "auto")} />}
          {message.result?.artifacts.filter(tool => tool.type === "permission" && tool.status === "awaiting_approval").map((tool, i) => <div className="capability-request" key={i}><p>Allow <code>{String(tool.data.capability)}</code> for this task and retry with the same context?</p><button className="secondary-button" disabled={chat.busy} onClick={() => chat.approve(String(tool.data.capability))}>Allow once and retry</button></div>)}
          {message.result?.change_id && <button className="view-diff-button" onClick={() => onDiff(message.result!.change_id!)}><FileCode2 size={14} />Review proposed changes<ArrowRight size={13} /></button>}
          {canResume && message.result && (message.result.task_status === "PAUSED" || message.result.status === "paused") && <PausedTaskCard result={message.result} busy={chat.busy} onResume={model => chat.resume(message.result!.run_id, model)} onCancel={() => void chat.cancel(message.result!.run_id)} onDiff={onDiff} />}
          {canResume && message.result?.task_status !== "PAUSED" && message.result?.status !== "paused" && <button className="secondary-button" disabled={chat.busy} onClick={() => chat.resume(message.result!.run_id)}>Resume saved task</button>}
          {message.result?.diagnostics && Object.keys(message.result.diagnostics).length > 0 && <details className="inspected-evidence"><summary>Run diagnostics · {String(message.result.diagnostics.tool_calls || 0)} tools · {String(message.result.diagnostics.current_stage || "")}</summary><dl>{["complexity", "total_steps", "llm_calls", "tool_calls", "read_calls", "search_calls", "write_calls", "execution_calls", "test_calls", "retry_count", "cache_hits", "repeated_calls", "agent_name", "current_stage", "last_tool"].map(key => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{String(message.result!.diagnostics![key] ?? "—")}</dd></div>)}</dl></details>}
          {!!message.result?.evidence.length && <details className="inspected-evidence"><summary>{message.result.evidence.length} inspected sources <span>· {message.result.confidence.toLowerCase()} confidence</span></summary><div>{message.result.evidence.map((e, i) => <button key={i} title={e.sha256} onClick={() => onSource(e.file, e.start_line)}><FileCode2 size={11} />{e.file}:{e.start_line}–{e.end_line}</button>)}</div><p>Source coverage is recorded. Model claims are not proof of correctness.</p></details>}
        </article>;
      })}
      {chat.error && <div className="inline-error" role="alert">{chat.error}</div>}
    </div>
    <ChatComposer project={project} conversationId={chat.conversationId} health={health} busy={chat.busy} attached={attached} selection={selected} onSend={(...args) => { follow.current = true; onSend(...args); }} onSteer={text => {void chat.steer(text);}} onStop={chat.stop} onRemove={onRemove} onRemoveSelection={onRemoveSelection} onAttach={onAttach} />
  </div>;
}
