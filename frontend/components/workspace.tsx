"use client";
import { useEffect, useRef, useState } from "react";
import { Code2, FolderOpen, FilePlus2, FolderPlus, Search, Settings2, TerminalSquare, GitBranch, X, AlertCircle } from "lucide-react";
import { useProject } from "@/hooks/use-project";
import { useEditor, languageFor } from "@/hooks/use-editor";
import { useChat } from "@/hooks/use-chat";
import { api } from "@/services/api";
import { errorMessage, readStored, writeStored } from "@/services/storage";
import { WorkspaceLayout } from "@/components/workspace/resizable-panels";
import { ProjectExplorer } from "@/components/project/project-explorer";
import { ProjectOpenDialog } from "@/components/project/project-open-dialog";
import { EditorWorkspace } from "@/editor/editor-workspace";
import { AssistantPanel } from "@/chat/assistant-panel";
import { AgentActivityTimeline } from "@/chat/activity-timeline";
import { DiffWorkspace } from "@/editor/diff-workspace";
import { WorkspaceWelcome } from "@/components/workspace/welcome";
import { NewProjectDialog } from "@/components/workspace/new-project-dialog";
import { FileDialog, type FileOperation } from "@/components/workspace/file-dialog";
import { CommandPalette, type PaletteCommand } from "@/components/workspace/command-palette";
import { BottomDock, type DockTab } from "@/components/workspace/bottom-dock";
import { TerminalView } from "@/components/workspace/terminal-view";
import { GitPanel } from "@/components/workspace/git-panel";
import { SearchPanel } from "@/components/workspace/search-panel";
import { CheckpointsPanel } from "@/components/workspace/checkpoints-panel";
import { ChecksPanel, type CommandEvidence } from "@/components/workspace/checks-panel";
import { PreferencesDialog } from "@/components/workspace/preferences-dialog";
import { HooksPanel } from "@/components/workspace/hooks-panel";
import type { ExplorerAction } from "@/components/file-tree";
import type { ChangeSet, ChatMode, Problem, SelectionContext } from "@/types";

export function Workspace() {
  const source = useProject(), editor = useEditor(source.project), chat = useChat(source.project?.id);
  const [dialog, setDialog] = useState(false), [creation, setCreation] = useState<"new" | "clone" | null>(null), [fileAction, setFileAction] = useState<FileOperation | null>(null);
  const [settings, setSettings] = useState(false), [home, setHome] = useState(false), [palette, setPalette] = useState<"command" | "file" | "symbol" | null>(null);
  const [attached, setAttached] = useState<string[]>([]), [selection, setSelection] = useState<SelectionContext | null>(null), [notes, setNotes] = useState("");
  const [diff, setDiff] = useState<string | null>(null), [editorFocus, setEditorFocus] = useState(0), [focus, setFocus] = useState<{target: "editor" | "assistant" | "restore"; token: number}>();
  const [tree, setTree] = useState<{path: string; kind: string}[]>([]), [syntax, setSyntax] = useState<Problem[]>([]), [markers, setMarkers] = useState<Problem[]>([]), [branch, setBranch] = useState("");
  const [dock, setDock] = useState<DockTab | null>(null), [maxDock, setMaxDock] = useState(false), [visited, setVisited] = useState<DockTab[]>([]);
  const [command, setCommand] = useState<{argv: string[]; token: number; projectId: string}>(), [execution, setExecution] = useState<CommandEvidence | null>(null);
  const [toast, setToast] = useState<{text: string; action?: () => void; label?: string} | null>(null);
  const pending = useRef<{text: string; mode: ChatMode; level: string; allowTests: boolean} | null>(null);
  const project = source.project, id = project?.id;
  const focusPane = (target: "editor" | "assistant" | "restore") => {setMaxDock(false); setFocus({target, token: Date.now()});};
  const openDock = (tab: DockTab) => {setDock(tab); setVisited(items => [...new Set([...items, tab])]); writeStored("forge-dock-tab", tab);};
  useEffect(() => {const saved = readStored<DockTab | null>("forge-dock-tab", null); if (saved) {setDock(saved); setVisited([saved]);}}, []);
  useEffect(() => {setAttached([]); setSelection(null); setDiff(null); setNotes(""); setSyntax([]); setMarkers([]); setTree([]); setBranch(""); setExecution(null); setCommand(undefined);}, [id]);
  useEffect(() => {
    if (!id) return; let cancelled = false;
    void Promise.allSettled([api<{path: string; kind: string}[]>(`/projects/${id}/tree`), api<{problems: Problem[]}>(`/projects/${id}/diagnostics`), api<{branch: string | null}>(`/projects/${id}/git`)]).then(([files, problems, git]) => {if (cancelled) return; if (files.status === "fulfilled") setTree(files.value); if (problems.status === "fulfilled") setSyntax(problems.value.problems); if (git.status === "fulfilled") setBranch(git.value.branch || "");});
    return () => {cancelled = true;};
  }, [id, project?.project_map.scanned_at]);
  useEffect(() => {setSelection(editor.selection);}, [editor.selection]);
  const openFile = (path: string, line?: number) => {setHome(false); setDiff(null); setEditorFocus(n => n + 1); if (!path.startsWith("untitled:")) setAttached(items => [...new Set([...items, path])].slice(-8)); void editor.open(path, line);};
  const newFile = () => {setHome(false); setDiff(null); editor.newScratch(); setEditorFocus(n => n + 1); if (!project) focusPane("editor");};
  const saveAs = () => {const f = editor.current; if (!f) return; const extension = f.language === "python" ? ".py" : f.language === "javascript" ? ".js" : ".txt"; setFileAction({kind: "save", path: f.path, value: f.scratch ? f.path.replace("untitled:", "") + extension : f.path});};
  const save = async () => {if (!editor.current) return; if (!project || editor.current.scratch) {saveAs(); return;} try {await editor.save(); await source.refresh(); setToast({text: "File saved"});} catch (err) {setToast({text: errorMessage(err)});}};
  const runFile = async () => {const f = editor.current; if (!f) return; if (!project || f.scratch) {saveAs(); setToast({text: "Save the file before running it."}); return;} if (!["python", "javascript"].includes(f.language)) {openDock("terminal"); setToast({text: "Use the project terminal or build script for this file type."}); return;} try {if (f.content !== f.original) await editor.save(); openDock("tests"); setCommand({argv: [f.language === "python" ? "python" : "node", f.path], token: Date.now(), projectId: project.id});} catch (err) {setToast({text: errorMessage(err)});}};
  const format = async () => {const f = editor.current; if (!f) return; try {const result = await api<{content: string}>(project ? `/projects/${project.id}/format` : "/editor/format", {method: "POST", body: JSON.stringify({path: f.scratch ? `source.${f.language === "python" ? "py" : "json"}` : f.path, content: f.content})}); editor.update(result.content); setToast({text: "Document formatted · save to write changes"});} catch (err) {setToast({text: errorMessage(err)});}};
  const viewDiff = (key: string) => {setHome(false); setDiff(key); setEditorFocus(n => n + 1);};
  const wasChatBusy = useRef(false);
  useEffect(() => {
    const completed = wasChatBusy.current && !chat.busy;
    wasChatBusy.current = chat.busy;
    const latest = chat.messages.at(-1)?.result;
    if (completed && latest?.change_id && !editor.files.some(file => file.content !== file.original)) viewDiff(latest.change_id);
  }, [chat.busy, chat.messages]);
  const send = (text: string, mode: ChatMode = "auto", level = "default", allowTests = false, selectedOverride?: SelectionContext) => {
    if (!source.health) return;
    if (!project) {pending.current = {text, mode, level, allowTests}; void source.create({name: "Agent workspace", template: "empty"}).then(() => setHome(false)).catch(err => setToast({text: errorMessage(err)})); return;}
    const f = editor.current, dirty = f && (f.scratch || f.content !== f.original);
    const requestSelection = selectedOverride || selection;
    const editorNote = dirty && requestSelection ? `UNSAVED EDITOR SELECTION (${f.path}, lines ${requestSelection.start_line}-${requestSelection.end_line}; not verified on disk):\n${requestSelection.text || ""}` : "";
    const mentions = [...text.matchAll(/@([\w./-]+)/g)].flatMap(match => project.project_map.files.filter(file => file.path === match[1] || file.path.startsWith(match[1].replace(/\/$/, "") + "/")).map(file => file.path));
    const workingDrafts = editor.files.filter(file => !file.scratch && file.projectId === project.id && file.content !== file.original).slice(0, 8).map(file => ({file: file.path, content: file.content, base_hash: file.baseHash}));
    void chat.send(text, mode, level, [...new Set([...attached, ...mentions])].filter(path => project.project_map.files.some(file => file.path === path)).slice(0, 8), requestSelection && !f?.scratch ? {...requestSelection, base_hash: editor.files.find(file => file.path === requestSelection.file)?.baseHash} : null, allowTests, undefined, [notes, editorNote].filter(Boolean).join("\n\n").slice(0, 24000), [], workingDrafts);
  };
  useEffect(() => {if (id && pending.current) {const task = pending.current; pending.current = null; send(task.text, task.mode, task.level, task.allowTests);}}, [id]);
  const explorerAction = (action: ExplorerAction, path: string, directory: boolean) => {
    if (action === "refresh") {void source.refresh(); return;}
    if (action === "open") {if (!directory) openFile(path); return;}
    if (action === "copy" || action === "relative") {void navigator.clipboard.writeText(action === "relative" ? path : `${project?.path.replaceAll("\\", "/")}/${path}`).then(() => setToast({text: "Path copied"})).catch(err => setToast({text: errorMessage(err)})); return;}
    if (action === "delete") {if (!id || !window.confirm(`Move ${path} to Forge trash? Open drafts in this path will close.`)) return; void api<{trash_id: string}>(`/projects/${id}/files/trash`, {method: "POST", body: JSON.stringify({path})}).then(async result => {editor.removed(path); await source.refresh(); setToast({text: "Moved to trash", label: "Undo", action: () => {void api(`/projects/${id}/trash/${result.trash_id}/restore`, {method: "POST"}).then(() => source.refresh()).catch(err => setToast({text: errorMessage(err)}));}});}).catch(err => setToast({text: errorMessage(err)})); return;}
    const parent = directory ? path : path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
    setFileAction({kind: action, path, value: action === "rename" || action === "move" ? path : parent ? parent + "/" : ""});
  };
  const submitFile = async (value: string, workspaceName: string) => {
    if (!fileAction) return; const target = project || await source.create({name: workspaceName, template: "empty"});
    if (fileAction.kind === "save") {const file = editor.current; if (file) await editor.save(target, value, file);}
    else if (fileAction.kind === "folder") await api(`/projects/${target.id}/folders`, {method: "POST", body: JSON.stringify({path: value})});
    else if (fileAction.kind === "file") {await api(`/projects/${target.id}/files/write`, {method: "POST", body: JSON.stringify({path: value, content: ""})}); openFile(value);}
    else {await api(`/projects/${target.id}/files/move`, {method: "POST", body: JSON.stringify({path: fileAction.path, destination: value})}); editor.renamed(fileAction.path || "", value);}
    await source.refresh(target.id); setHome(false); setEditorFocus(n => n + 1); setToast({text: fileAction.kind === "save" ? "File saved" : "Workspace updated"});
  };
  const reviewChanges = () => {focusPane("assistant"); send("Review my current changes. Inspect the actual Git diff, cite findings, and do not modify files.", "ask");};
  const commands: PaletteCommand[] = [
    {label: "New File", shortcut: "Ctrl N", run: newFile}, {label: "Save File", shortcut: "Ctrl S", run: () => {void save();}}, {label: "Save As", shortcut: "Ctrl Shift S", run: saveAs},
    {label: "New Project", run: () => setCreation("new")}, {label: "Open Folder", run: () => setDialog(true)}, {label: "Clone Repository", run: () => setCreation("clone")},
    {label: "Open Empty Workspace", run: () => {void source.create({name: "Untitled workspace", template: "empty"}).then(() => {setHome(false); focusPane("restore");}).catch(err => setToast({text: errorMessage(err)}));}},
    {label: "New Folder", run: () => setFileAction({kind: "folder"})}, {label: "Quick Open", shortcut: "Ctrl P", run: () => setPalette("file")}, {label: "Search in Files", shortcut: "Ctrl Shift F", run: () => openDock("search")}, {label: "Search Symbols", shortcut: "Ctrl Shift O", run: () => setPalette("symbol")},
    {label: "Open Terminal", shortcut: "Ctrl `", run: () => openDock("terminal")}, {label: "Run File", run: () => {void runFile();}}, {label: "Run Tests", run: () => {openDock("tests"); if (project) setCommand({argv: project.project_map.language.includes("python") ? ["python", "-m", "pytest", "-q"] : ["npm", "test"], token: Date.now(), projectId: project.id});}},
    {label: "Format Document", run: () => {void format();}}, {label: "Git Status", run: () => openDock("git")}, {label: "Review Current Changes", run: reviewChanges}, {label: "Restore Agent Checkpoint", run: () => openDock("checkpoints")},
    {label: "Focus Editor", run: () => focusPane("editor")}, {label: "Ask Forge", shortcut: "Ctrl Shift L", run: () => {focusPane("assistant"); document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message Forge"]')?.focus();}},
    {label: "Restore Layout", run: () => {setMaxDock(false); setDock(null); focusPane("restore");}}, {label: "Close Workspace", run: () => {source.close(); setHome(true);}}
  ];
  useEffect(() => {const handler = (event: KeyboardEvent) => {if (!(event.ctrlKey || event.metaKey) || event.isComposing || dialog || creation || fileAction || palette || settings) return; const key = event.key.toLowerCase(); let action: (() => void) | undefined;
    if (key === "n" && !event.shiftKey) action = newFile;
    else if (key === "s") action = event.shiftKey ? saveAs : () => {void save();};
    else if (key === "p") action = () => setPalette(event.shiftKey ? "command" : "file");
    else if (key === "f" && event.shiftKey) action = () => openDock("search");
    else if (key === "o" && event.shiftKey) action = () => setPalette("symbol");
    else if (key === "`" || event.code === "Backquote") action = () => dock === "terminal" ? setDock(null) : openDock("terminal");
    else if (key === "l" && event.shiftKey) action = commands.find(command => command.label === "Ask Forge")?.run;
    if (action) {event.preventDefault(); event.stopPropagation(); action();}
  }; window.addEventListener("keydown", handler, true); return () => window.removeEventListener("keydown", handler, true);});
  const agentProblems: Problem[] = [];
  for (const artifact of chat.messages.at(-1)?.result?.artifacts || []) {
    if (artifact.type === "tests" && artifact.data.status === "failed" && typeof artifact.data.stdout === "string") {
      for (const match of artifact.data.stdout.matchAll(/^([^\s:]+\.py):(\d+):\s*([^\n]*)/gm)) agentProblems.push({file: match[1], line: Number(match[2]), column: 1, message: match[3] || "Test failure", source: "pytest · VERIFIED", severity: "error"});
    }
    if (artifact.type === "security" && artifact.data.bandit && typeof artifact.data.bandit === "object") {
      const findings = (artifact.data.bandit as {findings?: {file: string; line: number; severity: string; message: string}[]}).findings || [];
      for (const finding of findings) agentProblems.push({file: finding.file, line: finding.line, column: 1, message: finding.message, source: "Bandit · VERIFIED", severity: finding.severity === "HIGH" ? "error" : "warning"});
    }
  }
  const allProblems = [...syntax.filter(item => !markers.some(marker => marker.file === item.file)), ...markers, ...agentProblems];
  const files = tree.filter(item => item.kind === "file").map(item => project?.project_map.files.find(file => file.path === item.path) || {path: item.path, language: languageFor(item.path), size: 0});
  const showHome = home || !project && !editor.files.length;
  return <main className={`workspace-shell ${maxDock && dock ? "dock-maximized" : ""}`}>
    <header className="topbar"><button className="brand" aria-label="Forge home" onClick={() => setHome(true)}><div className="brand-symbol"><Code2 size={19} /></div>forge</button><span className="header-slash">/</span><div className="header-project"><strong>{project?.name || "Workspaces"}</strong>{project && <button className="header-branch" onClick={() => openDock("git")}><GitBranch size={11} />{branch || "Git"}</button>}</div><button className="header-search" onClick={() => setPalette("file")}><Search size={12} />Search files or commands<kbd>Ctrl P</kbd></button><div className="topbar-actions"><span className={source.health ? "connection-badge connected" : "connection-badge"}><span />{source.health ? "Local" : "Offline"}</span><button className="icon-button" aria-label="New file" title="New file · Ctrl N" onClick={newFile}><FilePlus2 size={15} /></button><button className="icon-button" aria-label="New project" onClick={() => setCreation("new")}><FolderPlus size={15} /></button><button className="icon-button" aria-label="Workspace settings" onClick={() => setSettings(!settings)}><Settings2 size={15} /></button><button className="open-project-button" disabled={source.opening} onClick={() => setDialog(true)}><FolderOpen size={13} />Open folder</button></div></header>
    {settings && <PreferencesDialog projectId={id} onClose={() => setSettings(false)} />}
    {showHome ? <WorkspaceWelcome recent={source.recent} onProject={() => setCreation("new")} onOpen={() => setDialog(true)} onFile={newFile} onClone={() => setCreation("clone")} onEmpty={commands.find(command => command.label === "Open Empty Workspace")!.run} onRecent={key => {void source.reopen(key).then(() => {setHome(false); focusPane("restore");}).catch(err => setToast({text: errorMessage(err)}));}} /> : <WorkspaceLayout editorFocus={editorFocus} focusRequest={focus} onRestore={() => {setMaxDock(false); setDock(null);}}
      explorer={<ProjectExplorer project={project} active={editor.active} busy={source.opening} files={files.length ? files : undefined} directories={tree.filter(item => item.kind === "directory").map(item => item.path)} onAction={explorerAction} onOpen={openFile} onRefresh={() => {void source.refresh();}} onBrowse={() => setDialog(true)} />}
      editor={diff ? <DiffWorkspace id={diff} onClose={() => setDiff(null)} onUpdated={chat.updateChange} onCurrent={openFile} onRegenerate={path => {setDiff(null); send(`Regenerate the proposed edit for ${path} against its latest source. Preserve current manual changes and propose a targeted patch for review.`, "auto");}} onApplied={() => {void source.refresh(); void editor.refreshSaved(); setToast({text: "Approved changes saved. Editor, Explorer and Git status refreshed; unsaved drafts preserved."});}} /> : <EditorWorkspace project={project} editor={editor} onOpen={openFile} onBrowse={() => setDialog(true)} onPrompt={text => send(text)} onSelectionPrompt={(text, selected) => send(text, "auto", "default", false, selected)} onNew={newFile} onSave={() => {void save();}} onSaveAs={saveAs} onFormat={() => {void format();}} onRun={() => {void runFile();}} onProblems={items => setMarkers(previous => [...previous.filter(item => item.file !== editor.active), ...items])} onDraft={() => {const f = editor.current; if (f && !f.scratch) void chat.send(`Validate my editor draft for ${f.path}`, "auto", "intermediate", [f.path], null, false, {file: f.path, content: f.content, base_hash: f.baseHash});}} />}
      assistant={<div className="assistant-with-context">{notes && <div className="attached-note"><TerminalSquare size={12} /><span>Attached context · {notes.length} characters</span><button aria-label="Remove attached output" onClick={() => setNotes("")}><X size={12} /></button></div>}<AssistantPanel project={project} health={source.health} chat={chat} selected={selection} attached={attached} onSend={send} onRemove={path => {setAttached(items => items.filter(file => file !== path)); if (selection?.file === path) setSelection(null);}} onRemoveSelection={() => setSelection(null)} onAttach={path => setAttached(items => [...new Set([...items, path])].slice(-8))} onSource={openFile} onDiff={viewDiff} onBrowse={() => setDialog(true)} /></div>}
    />}
    <div className={`dock-wrapper ${maxDock ? "maximized" : ""}`} hidden={!dock}><BottomDock tab={dock || "terminal"} onTab={openDock} onClose={() => {setDock(null); setMaxDock(false);}} problems={allProblems.length} maximize={maxDock} onMaximize={() => setMaxDock(!maxDock)}>
      {visited.includes("terminal") && <div className="dock-pane" hidden={dock !== "terminal"}><TerminalView project={project} onAttach={text => {setNotes(`USER-ATTACHED TERMINAL OUTPUT (untrusted data):\n${text}`); setToast({text: "Terminal output attached to the next agent request"});}} /></div>}
      <div className="dock-pane" hidden={dock !== "problems"}><div className="dock-toolbar"><span>{allProblems.length} reported problems</span><button onClick={() => {void source.refresh();}}>Refresh syntax checks</button></div>{allProblems.map((problem, i) => <button className="problem-row" key={i} onClick={() => openFile(problem.file, problem.line)}><AlertCircle size={13} /><span>{problem.message}</span><code>{problem.file}:{problem.line}:{problem.column}</code><small>{problem.source}</small></button>)}{!allProblems.length && <p className="quiet-note">No editor or syntax problems reported. Run lint/type checks for additional diagnostics.</p>}</div>
      {visited.includes("tests") && <div className="dock-pane" hidden={dock !== "tests"}><ChecksPanel key={id || "none"} project={project} request={command} tools={chat.messages.at(-1)?.result?.artifacts || []} onSource={openFile} onDiff={viewDiff} onEvidence={result => {setExecution(result); const diagnostics = result.stdout.matchAll(/([^\s:]+\.(?:py|tsx?|jsx?)):(\d+):(\d+):\s*([^\n]+)/g); setMarkers(previous => [...previous.filter(item => item.source !== "command"), ...[...diagnostics].map(match => ({file: match[1], line: Number(match[2]), column: Number(match[3]), message: match[4], source: "command", severity: "error"}))]);}} /></div>}
      {visited.includes("git") && <div className="dock-pane" hidden={dock !== "git"}><GitPanel project={project} onSource={openFile} onReview={reviewChanges} onBranch={setBranch} canChangeWorkspace={() => !editor.files.some(file => file.content !== file.original || file.scratch)} onChanged={() => {void source.refresh(); void editor.refreshSaved();}} /></div>}
      {visited.includes("search") && <div className="dock-pane" hidden={dock !== "search"}><SearchPanel key={id} project={project} onSource={openFile} /></div>}
      {visited.includes("hooks") && <div className="dock-pane" hidden={dock !== "hooks"}><HooksPanel key={id} project={project} /></div>}
      {visited.includes("checkpoints") && <div className="dock-pane" hidden={dock !== "checkpoints"}><CheckpointsPanel project={project} onRestore={key => {void source.refresh(); void editor.refreshSaved(); setToast({text: "Checkpoint restored. Unsaved drafts preserved."}); void api<ChangeSet>(`/changes/${key}`).then(chat.updateChange);}} /></div>}
      <div className="dock-pane activity-dock" hidden={dock !== "activity"}><AgentActivityTimeline events={chat.events} running={chat.busy} />{!chat.events.length && <p className="quiet-note">Agent activity appears here while a task is running.</p>}{execution && <p className="quiet-note">Last workspace command exited with code {execution.exit_code}.</p>}</div>
    </BottomDock></div>
    <footer className="statusbar"><div><button onClick={() => openDock("terminal")}><TerminalSquare size={12} />Terminal</button><button onClick={() => openDock("problems")}><AlertCircle size={11} />{allProblems.length}</button><span>{source.opening ? "Indexing…" : project ? `${project.project_map.files.length} indexed files` : "Scratch editing ready"}</span></div><div>{source.health?.model || "Evidence mode"}<span className="status-separator" /><span>{project?.source_kind === "browser" ? "Imported copy" : "Local workspace"}</span></div></footer>
    {toast && <div className="workspace-toast" role="status"><span>{toast.text}</span>{toast.action && <button onClick={toast.action}>{toast.label}</button>}<button aria-label="Dismiss message" onClick={() => setToast(null)}><X size={12} /></button></div>}
    <ProjectOpenDialog open={dialog} recent={source.recent} opening={source.opening} onClose={() => {setDialog(false); setHome(false); focusPane("restore");}} onOpen={source.open} onRecent={source.reopen} />
    {creation && <NewProjectDialog clone={creation === "clone"} onClose={() => setCreation(null)} onCreate={async body => {await source.create(body); setHome(false); focusPane("restore");}} />}
    {fileAction && <FileDialog action={fileAction} projectName={project?.name} onClose={() => setFileAction(null)} onSubmit={submitFile} />}
    {palette && <CommandPalette mode={palette} commands={commands} files={files.map(file => file.path)} project={project} onOpen={openFile} onClose={() => setPalette(null)} />}
  </main>;
}
