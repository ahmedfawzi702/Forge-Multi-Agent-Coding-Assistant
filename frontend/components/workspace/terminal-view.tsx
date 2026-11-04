"use client";
import { useEffect, useRef, useState } from "react";
import { ClipboardPlus, Plus, Square, Eraser, TerminalSquare } from "lucide-react";
import { api } from "@/services/api";
import { errorMessage } from "@/services/storage";
import type { Project } from "@/types";
import type { Terminal } from "@xterm/xterm";

export function TerminalView({project, onAttach}: {project: Project | null; onAttach: (text: string) => void}) {
  const container = useRef<HTMLDivElement>(null), terminal = useRef<Terminal | null>(null);
  const currentId = useRef<string | null>(null), source = useRef<EventSource | null>(null), output = useRef("");
  const [session, setSession] = useState<string | null>(null), [sessions, setSessions] = useState<{id: string; status: string}[]>([]);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [closed, setClosed] = useState(false);
  const projectId = project?.id;
  const scope = useRef(projectId); scope.current = projectId;
  const attach = (id: string) => {
    if (scope.current !== projectId) return;
    source.current?.close(); terminal.current?.reset(); output.current = ""; currentId.current = id;
    setSession(id); setClosed(false); setError("");
    const stream = new EventSource(`/api/projects/${projectId}/terminal/${id}/events`); source.current = stream;
    stream.onmessage = event => { const data = JSON.parse(event.data); if (data.type === "output") {terminal.current?.write(data.data); output.current = (output.current + data.data).slice(-24000);} else if (data.type === "exit") {setClosed(true); stream.close(); terminal.current?.write("\r\n[Terminal closed]\r\n");} };
    stream.onerror = () => { setError("Terminal disconnected. Open a new session if the backend restarted."); stream.close(); };
    terminal.current?.focus();
  };
  useEffect(() => {
    let cancelled = false, observer: ResizeObserver | undefined, input: {dispose(): void} | undefined, resizeTimer: ReturnType<typeof setTimeout> | undefined;
    setSession(null); setError(""); currentId.current = null;
    void (async () => {
      const [{Terminal}, {FitAddon}] = await Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit")]);
      if (cancelled || !container.current || !projectId) return;
      const term = new Terminal({cursorBlink: true, fontSize: 12, fontFamily: "'Cascadia Code',Consolas,monospace", scrollback: 2000, convertEol: true, theme: {background: "#1e1e21", foreground: "#dfe1e5", cursor: "#54aeff", selectionBackground: "#2d415f"}});
      const fit = new FitAddon(); term.loadAddon(fit); term.open(container.current); terminal.current = term;
      observer = new ResizeObserver(() => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (cancelled) return; fit.fit(); const id = currentId.current; if (id) void api(`/projects/${projectId}/terminal/${id}/resize`, {method: "POST", body: JSON.stringify({cols: Math.max(20, Math.min(400, term.cols)), rows: Math.max(5, Math.min(200, term.rows))})}).catch(() => {}); }, 100); }); observer.observe(container.current); fit.fit();
      let queued = Promise.resolve();
      input = term.onData(data => { const id = currentId.current; if (!id) return; for (let start = 0; start < data.length; start += 16000) { const piece = data.slice(start, start + 16000); queued = queued.then(async () => { await api(`/projects/${projectId}/terminal/${id}/input`, {method: "POST", body: JSON.stringify({data: piece})}); }).catch(err => {if (!cancelled) setError(errorMessage(err));}); } });
      const items = await api<{id: string; status: string}[]>(`/projects/${projectId}/terminal`);
      if (!cancelled) {setSessions(items); const existing = items.find(item => item.status === "running"); if (existing) attach(existing.id);}
    })().catch(err => {if (!cancelled) setError(errorMessage(err));});
    return () => {cancelled = true; source.current?.close(); observer?.disconnect(); input?.dispose(); clearTimeout(resizeTimer); terminal.current?.dispose(); terminal.current = null;};
    // Each workspace owns its PTY; map refreshes do not replace a live terminal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);
  const create = async () => {
    if (!project) return; setBusy(true); setError("");
    try {const item = await api<{id: string}>(`/projects/${project.id}/terminal`, {method: "POST", body: JSON.stringify({approved: true, cols: Math.max(20, Math.min(400, terminal.current?.cols || 100)), rows: Math.max(5, Math.min(200, terminal.current?.rows || 24))})}); if (scope.current !== project.id) return; setSessions(items => [...items, {id: item.id, status: "running"}]); attach(item.id);}
    catch (err) {setError(errorMessage(err));} finally {setBusy(false);}
  };
  return <div className="terminal-view"><div className="terminal-toolbar"><span><TerminalSquare size={13} />Developer terminal {closed && "· closed"}</span><div>{sessions.length > 1 && <select aria-label="Terminal session" value={session || ""} onChange={e => attach(e.target.value)}>{sessions.map((item, i) => <option value={item.id} key={item.id}>Terminal {i + 1}</option>)}</select>}<button aria-label="Attach terminal output" disabled={!session} onClick={() => onAttach(output.current.replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, "").slice(-12000))}><ClipboardPlus size={13} /></button><button aria-label="Clear terminal" onClick={() => {terminal.current?.clear(); output.current = "";}}><Eraser size={13} /></button><button aria-label="New terminal session" disabled={!project || busy} onClick={create}><Plus size={14} /></button><button aria-label="Stop terminal session" disabled={!session || closed} onClick={async () => {try {await api(`/projects/${projectId}/terminal/${session}/close`, {method: "POST"}); setClosed(true);} catch (err) {setError(errorMessage(err));}}}><Square size={11} /></button></div></div>
    {error && <div className="inline-error" role="alert">{error}</div>}
    <div className="terminal-surface" ref={container} style={{visibility: session ? "visible" : "hidden"}} />
    {!session && <div className="terminal-start"><TerminalSquare size={22} /><strong>Your workspace shell</strong><p>{project ? "Commands start in this workspace and run with your local account's access. Agent commands use separate permissions." : "Create or open a workspace to start a terminal."}</p><button className="secondary-button" disabled={!project || busy} onClick={create}>{busy ? "Starting…" : "Start terminal"}</button></div>}
  </div>;
}
