"use client";
import { useEffect, useRef, useState, type ReactNode, type PointerEvent } from "react";
import { Code2, MessageSquare, PanelLeftClose, PanelLeftOpen, RotateCcw, Maximize2, Minimize2 } from "lucide-react";
import { readStored, writeStored } from "@/services/storage";

type Layout = { explorer: number; editor: number; hideExplorer: boolean; hideEditor: boolean; maximize: boolean; focusEditor: boolean };
const defaults: Layout = { explorer: 17, editor: 36, hideExplorer: false, hideEditor: false, maximize: false, focusEditor: false };

export function WorkspaceLayout({ explorer, editor, assistant, editorFocus, focusRequest, onRestore }: { explorer: ReactNode; editor: ReactNode; assistant: ReactNode; editorFocus: number; focusRequest?: {target: "editor" | "assistant" | "restore"; token: number}; onRestore?: () => void }) {
  const [layout, setLayout] = useState<Layout>(defaults);
  const [mobileTab, setMobileTab] = useState("assistant");
  const [mobileExplorer, setMobileExplorer] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  const drag = useRef<{ kind: "explorer" | "editor"; x: number; initial: Layout; width: number } | null>(null);
  useEffect(() => {
    const saved = readStored<Layout>("forge-layout-v2", defaults);
    if (Number.isFinite(saved.explorer) && Number.isFinite(saved.editor)) setLayout({ ...defaults, ...saved,
      explorer: Math.max(12, Math.min(26, saved.explorer)), editor: Math.max(20, Math.min(55, saved.editor)) });
  }, []);
  const change = (update: Partial<Layout>) => setLayout(current => { const next = { ...current, ...update }; writeStored("forge-layout-v2", next); return next; });
  useEffect(() => { if (focusRequest) { change({maximize: focusRequest.target === "assistant", focusEditor: focusRequest.target === "editor", hideEditor: false}); setMobileTab(focusRequest.target === "assistant" ? "assistant" : "editor"); } }, [focusRequest?.token]);
  useEffect(() => { if (editorFocus) { setLayout(current => ({ ...current, maximize: false, hideEditor: false })); setMobileTab("editor"); setMobileExplorer(false); } }, [editorFocus]);
  const start = (event: PointerEvent<HTMLDivElement>, kind: "explorer" | "editor") => {
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { kind, x: event.clientX, initial: layout, width: container.current?.clientWidth || 1 };
    document.body.classList.add("resizing");
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    const current = drag.current; if (!current) return;
    const delta = (event.clientX - current.x) / current.width * 100;
    if (current.kind === "explorer") change({ explorer: Math.max(12, Math.min(26, current.initial.explorer + delta)) });
    else change({ editor: Math.max(20, Math.min(65 - (layout.hideExplorer ? 0 : layout.explorer), current.initial.editor + delta)) });
  };
  const end = () => { drag.current = null; document.body.classList.remove("resizing"); };
  const separator = (kind: "explorer" | "editor") => <div className="pane-divider" role="separator" tabIndex={0} aria-label={`Resize ${kind} panel`} aria-orientation="vertical" aria-valuemin={kind === "explorer" ? 12 : 20} aria-valuemax={kind === "explorer" ? 26 : 55} aria-valuenow={layout[kind]}
    onPointerDown={e => start(e, kind)} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end}
    onDoubleClick={() => change({ [kind]: defaults[kind] })} onKeyDown={e => {
      if (["ArrowLeft", "ArrowRight", "Home"].includes(e.key)) { e.preventDefault(); change({ [kind]: e.key === "Home" ? defaults[kind] : Math.max(kind === "explorer" ? 12 : 20, Math.min(kind === "explorer" ? 26 : 50, layout[kind] + (e.key === "ArrowRight" ? 2 : -2))) }); }
    }}><span /></div>;
  const showExplorer = mobileExplorer || !layout.hideExplorer && !layout.maximize && !layout.focusEditor;
  const showEditor = layout.focusEditor || !layout.hideEditor && !layout.maximize;
  const showAssistant = !layout.focusEditor;
  const columns = layout.focusEditor ? "1fr" : [showExplorer ? `${layout.explorer}fr 5px` : "", showEditor ? `${layout.editor}fr 5px` : "", `${100 - (showExplorer ? layout.explorer : 0) - (showEditor ? layout.editor : 0)}fr`].filter(Boolean).join(" ");
  return <><div className="workspace-controls"><div className="layout-controls"><button aria-label="Toggle explorer" aria-pressed={showExplorer} onClick={() => { if (window.matchMedia("(max-width: 900px)").matches) setMobileExplorer(!mobileExplorer); else change({ hideExplorer: !showExplorer, maximize: false }); }}>{showExplorer ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}<span>Explorer</span></button><button aria-label="Toggle editor" aria-pressed={showEditor} onClick={() => change({ hideEditor: !showEditor, maximize: false })}><Code2 size={14} /><span>Editor</span></button></div>
    <div className="mobile-switch"><button className={mobileTab === "editor" ? "active" : ""} onClick={() => { setMobileTab("editor"); change({ hideEditor: false, maximize: false }); }}><Code2 size={13} />Code</button><button className={mobileTab === "assistant" ? "active" : ""} onClick={() => setMobileTab("assistant")}><MessageSquare size={13} />Assistant</button></div>
    <div className="layout-controls"><button aria-label="Maximize editor" onClick={() => change({focusEditor: !layout.focusEditor, maximize: false})}><Code2 size={13} /><span>{layout.focusEditor ? "Restore editor" : "Focus editor"}</span></button><button aria-label="Restore workspace layout" onClick={() => {change(defaults); onRestore?.();}}><RotateCcw size={13} /><span>Restore</span></button><button aria-label={layout.maximize ? "Restore panels" : "Maximize assistant"} onClick={() => change({ maximize: !layout.maximize, focusEditor: false })}>{layout.maximize ? <Minimize2 size={13} /> : <Maximize2 size={13} />}<span>{layout.maximize ? "Restore panels" : "Focus assistant"}</span></button></div></div>
    <div ref={container} className={`resizable-workbench mobile-${mobileTab} ${mobileExplorer ? "mobile-explorer-open" : ""} ${layout.maximize ? "assistant-maximized" : ""}`} style={{ gridTemplateColumns: columns }}>
      {showExplorer && <><aside className="explorer-pane">{explorer}</aside>{separator("explorer")}</>}
      {showEditor && <><section className="editor-pane">{editor}</section>{showAssistant && separator("editor")}</>}
      {showAssistant && <section className="assistant-pane">{assistant}</section>}
    </div></>;
}
