"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { GitBranch, Plus, Minus, RefreshCw, WandSparkles } from "lucide-react";
import { api } from "@/services/api";
import { errorMessage } from "@/services/storage";
import { CodeDiff } from "@/editor/code-diff";
import { loadMonaco } from "@/editor/code-editor";
import type { Project } from "@/types";

type GitStatus = {repository: boolean; branch: string | null; files: {path: string; status: string; staged: boolean}[]};
type Details = {branches: string[]; remotes: {name: string; url: string}[]; history: string[]; upstream: string | null; ahead_behind: string[] | null; authentication: string};
type Target = {remote: string; url: string; branch: string; head: string; uncommitted_files: number};
export function GitPanel({project, onSource, onReview, onBranch, onChanged, canChangeWorkspace}: {project: Project | null; onSource: (path: string) => void; onReview: () => void; onBranch: (branch: string) => void; onChanged: () => void; canChangeWorkspace: () => boolean}) {
  const [git, setGit] = useState<GitStatus | null>(null), [details, setDetails] = useState<Details | null>(null);
  const [message, setMessage] = useState(""), [branch, setBranch] = useState(""), [remote, setRemote] = useState("origin");
  const [patch, setPatch] = useState(""), [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState<{path: string; current: string; incoming: string} | null>(null);
  const id = project?.id, scope = useRef(id); scope.current = id;
  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      const status = await api<GitStatus>(`/projects/${id}/git`);
      const extra = status.repository ? await api<Details>(`/projects/${id}/git/details`) : null;
      if (scope.current !== id) return;
      setGit(status); setDetails(extra); onBranch(status.branch || ""); setError("");
    } catch (err) {if (scope.current === id) setError(errorMessage(err));}
  }, [id]);
  useEffect(() => {setGit(null); setDetails(null); setPatch(""); setConflict(null); setNotice(""); void refresh();}, [refresh, project?.project_map.scanned_at]);
  const action = async (action: string, paths: string[] = [], selectedBranch = branch) => {
    if (!id) return;
    if (["switch", "pull", "abort_merge"].includes(action) && !canChangeWorkspace()) {setError("Save or close unsaved editor drafts before changing the Git working tree."); return;}
    setBusy(true); setError(""); setNotice("");
    try {
      let approve_hooks = false, confirmed = false, expected_url: string | undefined, expected_head: string | undefined;
      if (action === "commit") {
        const hooks = await api<{hooks: {event: string}[]}>(`/projects/${id}/hooks`);
        if (hooks.hooks.some(hook => hook.event === "BeforeCommit")) {
          if (!window.confirm("Run configured BeforeCommit hooks locally before committing? Project code can access this machine.")) return;
          approve_hooks = true;
        }
      }
      if (["fetch", "pull", "push"].includes(action)) {
        const target = await api<Target>(`/projects/${id}/git/target?remote=${encodeURIComponent(remote)}&push=${action === "push"}`);
        if (scope.current !== id) return;
        selectedBranch = target.branch; expected_url = target.url; expected_head = target.head;
        confirmed = window.confirm(`${action.toUpperCase()} ${target.branch}\n${target.url}\nCommit: ${target.head}\n${target.uncommitted_files} uncommitted files${action === "push" ? " (not included in this push)" : ""}.\n${action === "pull" ? "Fast-forward only. " : ""}Proceed?`);
        if (!confirmed) return;
      }
      if (action === "abort_merge") {confirmed = window.confirm("Abort this merge? Git will attempt to restore the pre-merge working tree. Save any resolution you want to keep first."); if (!confirmed) return;}
      const result = await api<{remote_verified?: boolean}>(`/projects/${id}/git`, {method: "POST", body: JSON.stringify({action, paths, message, branch: selectedBranch, remote, confirmed, expected_url, expected_head, approve_hooks})});
      if (scope.current !== id) return;
      if (action === "commit") setMessage("");
      if (action === "branch") setBranch("");
      setNotice(action === "push" && result.remote_verified ? "Push succeeded. Remote branch commit verified." : `${action} completed.`);
      if (["switch", "pull", "abort_merge"].includes(action)) onChanged();
      await refresh();
    } catch (err) {if (scope.current === id) setError(errorMessage(err));}
    finally {if (scope.current === id) setBusy(false);}
  };
  const generate = async (pr = false) => {
    if (!id) return; setBusy(true); setError("");
    try {const result = await api<{message: string}>(`/projects/${id}/git/${pr ? "pr-description" : "message"}`, {method: "POST"}); if (scope.current === id) {if (pr) setPatch(result.message); else setMessage(result.message);}}
    catch (err) {if (scope.current === id) setError(errorMessage(err));} finally {if (scope.current === id) setBusy(false);}
  };
  const conflicts = async (path: string) => {
    if (!id) return;
    try {const result = await api<{base: string; current: string; incoming: string}>(`/projects/${id}/git/conflicts?path=${encodeURIComponent(path)}`); await loadMonaco(); if (scope.current === id) {setConflict({path, current: result.current, incoming: result.incoming}); setPatch(`CONFLICT: ${path}\n\nBASE\n${result.base}\n\nEdit the working file, save, review, then stage your resolution.`); onSource(path);}}
    catch (err) {setError(errorMessage(err));}
  };
  return <div className="git-panel">
    <div className="dock-toolbar"><span><GitBranch size={14} />{git?.branch || "Source control"}</span><button aria-label="Refresh Git status" disabled={!id || busy} onClick={refresh}><RefreshCw size={13} /></button><button className="secondary-button" disabled={!git?.repository || busy} onClick={onReview}>Review changes</button></div>
    {error && <div className="inline-error" role="alert">{error}</div>}{notice && <p role="status">{notice}</p>}
    {!project ? <p className="quiet-note">Open a workspace to use Git.</p> : git && !git.repository ? <div className="dock-empty"><p>This workspace has no Git repository.</p><button className="secondary-button" onClick={() => action("init")} disabled={busy}>Initialize repository</button></div> : <>
      <div className="git-workbench"><div className="git-changes">{git?.files.map(file => <div key={file.path}>
        <span className="git-state">{file.status}</span><button onClick={async () => {onSource(file.path); try {const diff = await api<{patch: string}>(`/projects/${id}/git/diff?staged=${file.staged}`); if (scope.current === id) setPatch(diff.patch || "No textual diff. Untracked files can be opened in the editor.");} catch (err) {setError(errorMessage(err));}}}>{file.path}</button>
        {(/U/.test(file.status) || ["AA", "DD"].includes(file.status)) && <button onClick={() => conflicts(file.path)}>Review conflict</button>}
        <button aria-label={`${file.staged ? "Unstage" : "Stage"} ${file.path}`} disabled={busy} onClick={() => action(file.staged ? "unstage" : "stage", [file.path])}>{file.staged ? <Minus size={12} /> : <Plus size={12} />}</button>
      </div>)}{git?.files.length === 0 && <p className="quiet-note">Working tree clean.</p>}</div>
      <div className="git-edit-actions"><textarea aria-label="Commit message" placeholder="Commit message" value={message} onChange={e => setMessage(e.target.value)} /><div><button className="secondary-button" disabled={busy || !git?.files.some(file => file.staged)} onClick={() => generate()}><WandSparkles size={12} />Suggest message</button><button className="secondary-button" disabled={busy || !message.trim()} onClick={() => action("commit")}>Commit staged changes</button></div>
        <div><input aria-label="New Git branch" placeholder="New branch name" value={branch} onChange={e => setBranch(e.target.value)} /><button className="secondary-button" disabled={busy || !branch.trim()} onClick={() => action("branch")}>Create branch</button></div>
        <select aria-label="Switch Git branch" value={git?.branch || ""} disabled={busy} onChange={e => action("switch", [], e.target.value)}><option value={git?.branch || ""}>{git?.branch || "Choose branch"}</option>{details?.branches.filter(b => b !== git?.branch).map(b => <option key={b}>{b}</option>)}</select>
        <select aria-label="Git remote" value={remote} onChange={e => setRemote(e.target.value)}>{!details?.remotes.length && <option>origin</option>}{details?.remotes.map(r => <option key={r.name} value={r.name}>{r.name} · {r.url}</option>)}</select>
        <div>{["fetch", "pull", "push"].map(operation => <button key={operation} className="secondary-button" disabled={busy || !details?.remotes.length} onClick={() => action(operation)}>{operation === "push" ? "Push to GitHub / remote" : operation === "pull" ? "Pull (fast-forward)" : "Fetch"}</button>)}</div>
        <button className="text-button" disabled={busy} onClick={() => generate(true)}>Prepare PR description (does not create a PR)</button>
        {git?.files.some(f => /U/.test(f.status) || ["AA", "DD"].includes(f.status)) && <button className="text-button" disabled={busy} onClick={() => action("abort_merge")}>Abort merge…</button>}
        <small>{details?.authentication}</small><small>{details?.upstream ? `Upstream: ${details.upstream} · ahead/behind ${details.ahead_behind?.join(" / ") || "unknown"}` : "No upstream configured. Remote actions explicitly target the current branch."}</small>
      </div></div>
      <details><summary>Commit history</summary><pre className="git-patch">{details?.history.join("\n") || "No commits yet."}</pre></details>
      {conflict && <section aria-label="Conflict comparison"><p>Current branch (left) · Incoming (right) · {conflict.path}</p><div className="git-conflict-diff"><CodeDiff before={conflict.current} after={conflict.incoming} path={conflict.path} /></div><button className="secondary-button" onClick={() => onSource(conflict.path)}>Edit working file resolution</button></section>}
      {patch && <pre className="git-patch">{patch}</pre>}
    </>}
  </div>;
}
