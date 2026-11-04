"use client";
import { useEffect, useRef, useState } from "react";
import { loadMonaco } from "@/editor/code-editor";
import { FORGE_EDITOR_THEME } from "@/editor/theme";

/** Own both models so teardown detaches the diff before disposing its source. */
export function CodeDiff({ before, after, path }: { before: string; after: string; path: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false, dispose = () => {};
    setError("");
    void loadMonaco().then(() => {
      const monaco = window.forgeMonaco;
      if (cancelled || !container.current || !monaco) return;
      const extension = path.split(".").at(-1) || "";
      const language = ({ py: "python", ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript", json: "json", md: "markdown", html: "html", css: "css", yml: "yaml", yaml: "yaml", sql: "sql", java: "java", rs: "rust", go: "go", cs: "csharp", cpp: "cpp", c: "c", toml: "ini" } as Record<string, string>)[extension] || "plaintext";
      const original = monaco.editor.createModel(before, language);
      const modified = monaco.editor.createModel(after, language);
      const instance = monaco.editor.createDiffEditor(container.current, {
        theme: FORGE_EDITOR_THEME,
        readOnly: true, renderSideBySide: true, useInlineViewWhenSpaceIsLimited: false, minimap: { enabled: false },
        automaticLayout: true, fontSize: 12, scrollBeyondLastLine: false,
      });
      instance.setModel({ original, modified });
      dispose = () => {
        instance.setModel(null);
        instance.dispose();
        original.dispose();
        modified.dispose();
      };
    }).catch(e => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; dispose(); };
  }, [before, after, path]);
  return <div ref={container} style={{ height: "100%", width: "100%" }} aria-label={`Diff for ${path}`}>{error && <div className="editor-error" role="alert">{error}</div>}</div>;
}
