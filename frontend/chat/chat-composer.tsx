"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, ShieldCheck, SlidersHorizontal, Square, WandSparkles } from "lucide-react";
import { ContextBar } from "@/chat/context-bar";
import type { ChatMode, Health, Project, SelectionContext } from "@/types";

export function ChatComposer({ project, health, busy, attached, selection, conversationId, onSend, onSteer, onStop, onRemove, onRemoveSelection, onAttach }: {
  project: Project | null; health: Health | null; busy: boolean; attached: string[]; selection: SelectionContext | null;
  conversationId?: string;
  onSend: (text: string, mode: ChatMode, level: string, allowTests: boolean) => void; onStop: () => void;
  onSteer: (text: string) => void;
  onRemove: (path: string) => void; onRemoveSelection: () => void; onAttach: (path: string) => void;
}) {
  const [draft, setDraft] = useState(""), [mode, setMode] = useState<ChatMode>("auto"), [level, setLevel] = useState("default");
  const [options, setOptions] = useState(false), [allowTests, setAllowTests] = useState(false);
  const permissionScope = useRef({ project: project?.id, conversation: conversationId });
  useEffect(() => {
    const previous = permissionScope.current;
    if (previous.project !== project?.id || previous.conversation && previous.conversation !== conversationId) setAllowTests(false);
    permissionScope.current = { project: project?.id, conversation: conversationId };
  }, [project?.id, conversationId]);
  const enabled = !!health;
  const send = () => { if (!enabled || !draft.trim()) return; if (busy) onSteer(draft.trim()); else onSend(draft.trim(), mode, level, allowTests); setDraft(""); };
  return <div className="composer-area"><div className="composer">
    <ContextBar project={project} attached={attached} selection={selection} onRemove={onRemove} onRemoveSelection={onRemoveSelection} onAttach={onAttach} />
    <textarea aria-label="Message Forge" placeholder={busy ? "Send an update at the next safe boundary…" : project ? "Ask Forge to build, debug, explain, review…" : "Describe a project to build from scratch…"} value={draft} disabled={!enabled} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} />
    <div className="composer-tools"><WandSparkles size={12} /><select aria-label="Interaction mode" value={mode} onChange={e => setMode(e.target.value as ChatMode)}><option value="auto">Auto</option><option value="ask">Ask</option><option value="plan">Plan</option></select><span className="composer-mode-hint">{mode === "auto" ? "Plans & proposes changes" : mode === "ask" ? "Read only" : "Plan without changes"}</span><div className="composer-spacer" /><button className={`icon-button ${options ? "active" : ""}`} aria-label="Conversation options" aria-expanded={options} onClick={() => setOptions(!options)}><SlidersHorizontal size={14} /></button><button className="send-button" aria-label={busy ? "Stop response" : "Send message"} disabled={!busy && (!enabled || !draft.trim())} onClick={busy ? onStop : send}>{busy ? <Square size={13} fill="currentColor" /> : <ArrowUp size={17} />}</button></div>
    {busy && draft.trim() && <button className="secondary-button steering-send" onClick={send}>Send update</button>}
  </div>
  {options && <div className="conversation-options"><label>Explanation detail<select aria-label="Explanation level" value={level} onChange={e => setLevel(e.target.value)}><option value="default">Use agent settings</option><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label><label className="execution-choice"><input type="checkbox" checked={allowTests} disabled={mode !== "auto"} onChange={e => setAllowTests(e.target.checked)} /><span>Allow agent commands and tests for this conversation</span></label><p>Commands and tests execute project code with access to this machine. Source is copied to a validation workspace; this is not an OS sandbox. Ask and Plan never execute tests.</p></div>}
  <div className="composer-footer"><ShieldCheck size={11} /><span>{project?.source_kind === "browser" ? "Source snapshot · original folder protected" : "Review diffs before applying"}</span><span className="composer-model" title={health?.model || "No model connected"}>{health?.model?.split("/").at(-1) || "Evidence mode"}</span><span>↵ send · ⇧↵ new line</span></div></div>;
}
