"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Maximize2, Minimize2, X } from "lucide-react";
import { readStored, writeStored } from "@/services/storage";

export type DockTab = "terminal" | "problems" | "tests" | "activity" | "git" | "search" | "checkpoints" | "hooks";
const tabs: [DockTab, string][] = [["terminal", "Terminal"], ["problems", "Problems"], ["tests", "Tests & checks"], ["activity", "Agent activity"], ["git", "Git"], ["search", "Search"], ["checkpoints", "Checkpoints"], ["hooks", "Hooks"]];
export function BottomDock({tab, onTab, onClose, children, problems, maximize, onMaximize}: {tab: DockTab; onTab: (tab: DockTab) => void; onClose: () => void; children: ReactNode; problems: number; maximize: boolean; onMaximize: () => void}) {
  const [height, setHeight] = useState(240), drag = useRef<{y: number; height: number} | null>(null);
  useEffect(() => {setHeight(readStored("forge-dock-height", 240));}, []);
  const change = (value: number) => {const next = Math.max(140, Math.min(window.innerHeight - 160, value)); setHeight(next); writeStored("forge-dock-height", next);};
  return <section className={`bottom-dock ${maximize ? "maximized" : ""}`} style={{height: maximize ? undefined : height}}>
    {!maximize && <div role="separator" aria-label="Resize bottom panel" aria-orientation="horizontal" aria-valuenow={height} tabIndex={0} className="dock-resizer" onPointerDown={e => {e.currentTarget.setPointerCapture(e.pointerId); drag.current = {y: e.clientY, height};}} onPointerMove={e => {if (drag.current) change(drag.current.height + drag.current.y - e.clientY);}} onPointerUp={() => {drag.current = null;}} onPointerCancel={() => {drag.current = null;}} onKeyDown={e => {if (["ArrowUp", "ArrowDown", "Home"].includes(e.key)) {e.preventDefault(); change(e.key === "Home" ? 240 : height + (e.key === "ArrowUp" ? 20 : -20));}}} />}
    <div className="dock-tabs" role="tablist">{tabs.map(([id, title]) => <button role="tab" aria-selected={tab === id} key={id} onClick={() => onTab(id)}>{title}{id === "problems" && problems > 0 && <span>{problems}</span>}</button>)}<span className="dock-spacer" /><button aria-label={maximize ? "Restore bottom panel" : "Maximize bottom panel"} onClick={onMaximize}>{maximize ? <Minimize2 size={13} /> : <Maximize2 size={13} />}</button><button aria-label="Close bottom panel" onClick={onClose}><X size={14} /></button></div>
    <div className="dock-content">{children}</div>
  </section>;
}
