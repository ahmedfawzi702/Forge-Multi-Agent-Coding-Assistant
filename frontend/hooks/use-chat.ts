"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamChat } from "@/services/api";
import { errorMessage, readStored, writeStored } from "@/services/storage";
import type { AgentEvent, ChatMessage, ChatMode, ChatResult, SelectionContext, ChangeSet } from "@/types";

export function useChat(projectId?: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [conversations, setConversations] = useState<{ id: string; title: string }[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [changes, setChanges] = useState<Record<string, ChangeSet>>({});
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null), locked = useRef(false);
  const runId = useRef<string | null>(null);
  const retry = useRef<((capability: string) => void) | null>(null);
  const currentProject = useRef(projectId); currentProject.current = projectId;
  const history = useCallback(async (id: string) => {
    if (!projectId || currentProject.current !== projectId || locked.current) return;
    try {
      const data = await api<ChatMessage[]>(`/projects/${projectId}/conversations/${id}`);
      if (currentProject.current !== projectId) return;
      setMessages(data); setConversationId(id); setError(""); writeStored(`forge-chat-${projectId}`, id);
      for (const message of data) if (message.result?.change_id) {
        void api<ChangeSet>(`/changes/${message.result.change_id}`).then(change => {
          if (currentProject.current === projectId) setChanges(items => ({ ...items, [change.id]: change }));
        }).catch(() => {});
      }
    } catch (e) { setError(errorMessage(e)); }
  }, [projectId]);
  useEffect(() => {
    controller.current?.abort(); locked.current = false; setBusy(false); setMessages([]); setEvents([]); setChanges({}); setError(""); setConversationId(undefined);
    if (!projectId) return;
    let cancelled = false;
    void api<{ id: string; title: string }[]>(`/projects/${projectId}/conversations`).then(async data => {
      if (cancelled) return; setConversations(data);
      const last = readStored<string | null>(`forge-chat-${projectId}`, null);
      if (last && data.some(c => c.id === last)) await history(last);
    }).catch(() => setConversations([]));
    return () => { cancelled = true; controller.current?.abort(); };
  }, [projectId, history]);

  const send = async (text: string, mode: ChatMode, level: string, files: string[], selection: SelectionContext | null, allowExecution: boolean, draft?: { file: string; content: string; base_hash: string }, contextNotes = "", approvals: string[] = [], workingDrafts: {file: string; content: string; base_hash: string}[] = [], resumeRunId?: string, model?: string) => {
    if (!projectId || locked.current) return;
    retry.current = capability => {void send(text, mode, level, files, selection, allowExecution, draft, contextNotes, [...new Set([...approvals, capability])], workingDrafts, resumeRunId, model);};
    locked.current = true; const abort = new AbortController(); controller.current = abort;
    runId.current = null;
    setBusy(true); setError(""); setEvents([]);
    setMessages(items => [...items, { role: "user", content: text }, { role: "assistant", content: "", events: [] }]);
    const received: AgentEvent[] = [];
    try {
      await streamChat({ project_id: projectId, conversation_id: conversationId, message: text, mode, level: level === "default" ? undefined : level,
        selected_files: files, selected_code: selection,
        allow_execution: mode === "ask" || mode === "plan" ? false : allowExecution, editor_draft: draft, context_notes: contextNotes, approvals, working_drafts: workingDrafts, resume_run_id: resumeRunId, model }, abort.signal, event => {
        if (currentProject.current !== projectId) return;
        received.push(event); setEvents([...received]);
        if (event.type === "task_started" && event.data.conversation_id) {
          runId.current = String(event.data.run_id);
          const id = String(event.data.conversation_id); setConversationId(id); writeStored(`forge-chat-${projectId}`, id);
        }
        if (event.type === "result") {
          const result = event.data as unknown as ChatResult;
          setConversationId(result.conversation_id); writeStored(`forge-chat-${projectId}`, result.conversation_id);
          setMessages(items => [...items.slice(0, -1), { role: "assistant", content: result.answer, result, events: [...received] }]);
        } else if (event.type !== "done" && event.type !== "task_completed") {
          setMessages(items => items.length ? [...items.slice(0, -1), { ...items[items.length - 1], events: [...received] }] : items);
        }
      });
    } catch (e) {
      if (currentProject.current !== projectId) return;
      const message = abort.signal.aborted ? "Task stopped. Staged progress is preserved; open this conversation from history to resume." : errorMessage(e);
      setError(message); setMessages(items => [...items.slice(0, -1), { role: "assistant", content: message, events: [...received] }]);
    } finally {
      if (currentProject.current === projectId) {
        setBusy(false); locked.current = false; controller.current = null;
        void api<{ id: string; title: string }[]>(`/projects/${projectId}/conversations`).then(setConversations).catch(() => {});
      }
    }
  };
  const steer = async (message: string) => {
    if (!runId.current || !locked.current) {setError("Wait for the task to start before sending an update."); return;}
    try {
      await api(`/runs/${runId.current}/steer`, {method: "POST", body: JSON.stringify({message})});
      if (currentProject.current !== projectId) return;
      setMessages(items => [...items.slice(0, -1), {role: "user", content: message}, items[items.length - 1]]);
    } catch (e) {setError(errorMessage(e));}
  };
  return { messages, conversations, conversationId, events, busy, error, send, steer, history, changes,
    resume: (runId: string, model?: string) => {void send("Continue from the preserved task checkpoint", "auto", "default", [], null, false, undefined, "", [], [], runId, model);},
    cancel: async (id: string) => {
      if (locked.current) return;
      try {
        await api(`/runs/${id}/cancel`, {method: "POST"});
        if (currentProject.current !== projectId) return;
        setMessages(items => items.map(message => message.result?.run_id === id ? {...message,
          content: "Task cancelled. Staged files remain available for inspection.",
          result: {...message.result, status: "cancelled", task_status: "CANCELLED", resumable: false, retryable: false}} : message));
      } catch (e) {setError(errorMessage(e));}
    },
    approve: (capability: string) => retry.current?.(capability),
    updateChange: (change: ChangeSet) => {
      setChanges(items => ({ ...items, [change.id]: change }));
      if (change.proposal.run_id) void api<{result?: ChatResult}>(`/runs/${change.proposal.run_id}`).then(run => {
        if (currentProject.current !== projectId || !run.result) return;
        setMessages(items => {
          const last = items.findLastIndex(item => item.result?.change_id === change.id);
          return items.map((item, index) => index === last ? {...item, result: run.result, content: run.result!.answer} : item);
        });
      }).catch(() => {});
    },
    stop: () => {if (runId.current) void api(`/runs/${runId.current}/stop`, {method: "POST"}).catch(() => {}); controller.current?.abort();}, newChat: () => {
      if (locked.current) return; setMessages([]); setEvents([]); setError(""); setConversationId(undefined);
      if (projectId) writeStored(`forge-chat-${projectId}`, null);
    } };
}
