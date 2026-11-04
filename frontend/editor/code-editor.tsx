"use client";

import { useEffect, useRef, useState } from "react";
import Editor, { loader, type OnMount } from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import type { SelectionContext, Problem } from "@/types";
import { FORGE_EDITOR_THEME, forgeEditorTheme } from "@/editor/theme";

type Monaco = typeof import("monaco-editor");
declare global {
  interface Window {
    forgeMonaco?: Monaco;
    MonacoEnvironment?: { getWorkerUrl: (moduleId: string, label: string) => string };
  }
}

let loading: Promise<void> | undefined;
export function loadMonaco(): Promise<void> {
  if (!loading) loading = new Promise((resolve, reject) => {
    window.MonacoEnvironment = { getWorkerUrl: (_, label) => `/monaco/${
      label === "json" ? "json" : ["css", "scss", "less"].includes(label) ? "css" :
      ["html", "handlebars", "razor"].includes(label) ? "html" :
      ["javascript", "typescript"].includes(label) ? "ts" : "editor"}.worker.js` };
    const link = document.createElement("link"); link.rel = "stylesheet"; link.href = "/monaco/editor.css"; document.head.appendChild(link);
    const script = document.createElement("script"); script.src = "/monaco/editor.js";
    script.onload = () => {
      if (!window.forgeMonaco) { loading = undefined; reject(new Error("Editor did not initialize")); return; }
      window.forgeMonaco.editor.defineTheme(FORGE_EDITOR_THEME, forgeEditorTheme);
      window.forgeMonaco.editor.setTheme(FORGE_EDITOR_THEME);
      loader.config({ monaco: window.forgeMonaco }); resolve();
    };
    script.onerror = () => { loading = undefined; reject(new Error("Editor assets could not load. Run npm run predev.")); };
    document.head.appendChild(script);
  });
  return loading;
}

export default function CodeEditor({ path, modelPath, content, language, line, findToken, command, onChange, onSelection, onAsk, onProblems, symbols = [] }: { path: string; modelPath?: string; content: string; language: string; line?: number; findToken?: number; command?: {id: string; token: number}; onChange?: (value: string) => void; onSelection?: (selection: SelectionContext | null) => void; onAsk?: (prompt: string, selection: SelectionContext) => void; onProblems?: (items: Problem[]) => void; symbols?: {name: string; type: string; start_line: number; end_line?: number}[] }) {
  const ref = useRef<editor.IStandaloneCodeEditor | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const latest = useRef({ path, onSelection, onAsk, onProblems, symbols }); latest.current = { path, onSelection, onAsk, onProblems, symbols };
  useEffect(() => {
    let mounted = true;
    void loadMonaco().then(() => { if (mounted) setReady(true); }).catch(e => { if (mounted) setError(String(e)); });
    return () => { mounted = false; };
  }, []);
  useEffect(() => {
    if (line && ref.current) {
      ref.current.revealLineInCenter(line);
      ref.current.setPosition({ lineNumber: line, column: 1 });
    }
  }, [line, path, content]);
  useEffect(() => { if (findToken) ref.current?.getAction("actions.find")?.run(); }, [findToken]);
  useEffect(() => { if (command && ref.current) { if (["undo", "redo"].includes(command.id)) ref.current.trigger("forge", command.id, null); else void ref.current.getAction(command.id)?.run(); } }, [command]);
  const mount: OnMount = (instance, monaco) => {
    ref.current = instance;
    if (line) instance.revealLineInCenter(line);
    const listener = instance.onDidChangeCursorSelection(event => {
      const model = instance.getModel(), selection = event.selection;
      latest.current.onSelection?.(!model || selection.isEmpty() ? null : {
        file: latest.current.path, start_line: selection.startLineNumber,
        end_line: selection.endLineNumber, start_column: selection.startColumn, end_column: selection.endColumn,
        text: model.getValueInRange(selection),
      });
    });
    const actions = [
      ["ask", "Ask Forge", "Explain this selected code and its surrounding context."],
      ["explain", "Explain Selection", "Explain this selected code."],
      ["fix", "Fix Selection", "Fix correctness and error handling in this selected code."],
      ["refactor", "Refactor Selection", "Refactor this selected code without changing behavior."],
      ["review", "Review Selection", "Review this selected code for regressions and edge cases."],
      ["tests", "Generate Tests", "Generate regression tests for this selected code; preserve its implementation."],
      ["docs", "Add Documentation", "Add documentation to this selected code."],
    ].map(([id, label, prompt], index) => instance.addAction({id: `forge.selection.${id}`, label, contextMenuGroupId: "forge", contextMenuOrder: index, precondition: "editorHasSelection", run: () => {
      const model = instance.getModel(), selected = instance.getSelection();
      if (!model || !selected || selected.isEmpty()) return;
      const value = {file: latest.current.path, start_line: selected.startLineNumber, end_line: selected.endLineNumber,
        start_column: selected.startColumn, end_column: selected.endColumn, text: model.getValueInRange(selected)};
      latest.current.onSelection?.(value);
      latest.current.onAsk?.(prompt, value);
    }}));
    const symbolProvider = monaco.languages.registerDocumentSymbolProvider("python", {provideDocumentSymbols: () => latest.current.symbols.map(symbol => ({name: symbol.name, detail: symbol.type, kind: symbol.type === "class" ? monaco.languages.SymbolKind.Class : monaco.languages.SymbolKind.Function, tags: [], range: new monaco.Range(symbol.start_line, 1, symbol.end_line || symbol.start_line, 1), selectionRange: new monaco.Range(symbol.start_line, 1, symbol.start_line, 1)}))});
    instance.onDidDispose(() => { listener.dispose(); symbolProvider.dispose(); actions.forEach(action => action.dispose()); });
  };
  if (error) return <div className="editor-error" role="alert">{error}</div>;
  if (!ready) return <div className="editor-loading">Loading local editor…</div>;
  return <Editor path={modelPath || path} language={language === "text" ? "plaintext" : language} value={content}
    onValidate={markers => latest.current.onProblems?.(markers.map(marker => ({file: latest.current.path, line: marker.startLineNumber, column: marker.startColumn, severity: marker.severity >= 8 ? "error" : "warning", message: marker.message, source: marker.source || "editor"})))}
    onMount={mount} onChange={value => onChange?.(value || "")} theme={FORGE_EDITOR_THEME} loading={<div className="editor-loading">Loading editor…</div>}
    options={{ readOnly: false, domReadOnly: false, minimap: { enabled: false }, fontSize: 13,
      fontFamily: "'Cascadia Code', 'SFMono-Regular', Consolas, monospace", lineHeight: 23,
      padding: { top: 20 }, scrollBeyondLastLine: false, wordWrap: "on", automaticLayout: true,
      renderLineHighlight: "gutter", overviewRulerLanes: 0, hideCursorInOverviewRuler: true,
      scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 } }} />;
}
