"use client";
import { useState } from "react";

export function PlanActions({plan, disabled, onImplement}: {plan: string; disabled: boolean; onImplement: (plan: string) => void}) {
  const [editing, setEditing] = useState(false), [text, setText] = useState(plan), [cancelled, setCancelled] = useState(false);
  if (cancelled) return <p className="quiet-note">Plan cancelled. No changes were made.</p>;
  return <div className="plan-actions">{editing && <textarea aria-label="Edit implementation plan" value={text} onChange={event => setText(event.target.value)} rows={12} />}
    <div><button className="primary-button" disabled={disabled || !text.trim()} onClick={() => onImplement(text)}>Implement plan</button>
      <button className="secondary-button" disabled={disabled} onClick={() => setEditing(!editing)}>{editing ? "Keep edited plan" : "Edit plan"}</button>
      <button className="text-button" disabled={disabled} onClick={() => setCancelled(true)}>Cancel plan</button></div></div>;
}
