"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/services/api";
import { errorMessage, readStored, writeStored } from "@/services/storage";
import type { OpenFile, Project, SelectionContext } from "@/types";

export function languageFor(path: string, content = "") {
  const ext = path.split(".").at(-1)?.toLowerCase() || "";
  const languages: Record<string, string> = { py: "python", ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript", json: "json", html: "html", css: "css", md: "markdown", sh: "shell", yml: "yaml", yaml: "yaml", toml: "ini", sql: "sql", rs: "rust", go: "go", java: "java", cs: "csharp", cpp: "cpp", c: "c" };
  if (languages[ext]) return languages[ext];
  if (/^\s*(?:def |import |from .+ import |print\(|#!.*python)/m.test(content)) return "python";
  if (/^\s*(?:const |let |function |import .* from )/m.test(content)) return "javascript";
  return "plaintext";
}
export function useEditor(project: Project | null) {
  const [allFiles, setFiles] = useState<OpenFile[]>([]), [active, setActive] = useState("");
  const [line, setLine] = useState<number>(), [selection, setSelection] = useState<SelectionContext | null>(null);
  const [loading, setLoading] = useState(false), [saving, setSaving] = useState(false), [error, setError] = useState("");
  const request = useRef(0), serial = useRef(0), filesRef = useRef(allFiles); filesRef.current = allFiles;
  const projectId = project?.id;
  const currentProject = useRef(projectId); currentProject.current = projectId;
  const files = allFiles.filter(f => f.scratch || f.projectId === projectId);
  const current = files.find(f => f.path === active);
  const same = (a: OpenFile, b: OpenFile) => a.path === b.path && a.projectId === b.projectId && !!a.scratch === !!b.scratch;
  const remember = (items: OpenFile[], id: string) => writeStored(`forge-tabs-${id}`, items.filter(f => f.projectId === id && !f.scratch).map(f => f.path));
  useEffect(() => {
    const recovered = readStored<OpenFile[]>("forge-drafts-v3", []).filter(f => typeof f.content === "string" && f.content.length <= 262144).slice(0, 20);
    setFiles(items => [...items, ...recovered.filter(f => !items.some(item => item.path === f.path && item.projectId === f.projectId))]);
    serial.current = recovered.length;
  }, []);
  useEffect(() => {
    const drafts = allFiles.filter(f => f.content !== f.original || f.scratch).slice(-20);
    if (drafts.reduce((n, f) => n + f.content.length, 0) < 1500000) writeStored("forge-drafts-v3", drafts);
  }, [allFiles]);
  const open = useCallback(async (path: string, targetLine?: number, fresh = false) => {
    const existing = filesRef.current.find(f => f.path === path && (f.scratch || f.projectId === project?.id));
    const token = ++request.current;
    setActive(path); setLine(targetLine); setSelection(null); setError("");
    if (!fresh && existing) { setLoading(false); return; }
    if (!project || path.startsWith("untitled:")) return;
    if (fresh && existing && existing.content !== existing.original) { setError("This editor has an unsaved draft. Save it or close it before reloading source."); return; }
    setLoading(true);
    try {
      const data = await api<{content: string; sha256: string}>(`/projects/${project.id}/file?path=${encodeURIComponent(path)}`);
      if (token !== request.current) return;
      setFiles(items => {
        const next = [...items.filter(f => !(f.path === path && f.projectId === project.id)), {path, projectId: project.id, content: data.content, original: data.content, baseHash: data.sha256, language: languageFor(path)}];
        remember(next, project.id); return next;
      });
    } catch (e) { if (token === request.current) setError(errorMessage(e)); }
    finally { if (token === request.current) setLoading(false); }
  }, [project]);
  useEffect(() => {
    request.current++; setActive(""); setSelection(null); setError(""); setLoading(false);
    if (!projectId) return;
    const saved = readStored<string[]>(`forge-tabs-${projectId}`, []).slice(0, 12);
    let cancelled = false;
    void (async () => { for (const path of saved) { if (cancelled) break; await open(path); } })();
    return () => { cancelled = true; request.current++; };
    // Refreshing the map must not discard editor drafts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);
  const newScratch = () => {
    const path = `untitled:Untitled-${++serial.current}`;
    setFiles(items => [...items, {path, content: "", original: "", language: "plaintext", baseHash: "", scratch: true}]);
    setActive(path); setSelection(null); setError(""); setLoading(false); request.current++;
    return path;
  };
  const close = (path: string) => {
    const file = files.find(f => f.path === path);
    if (file && file.content !== file.original && !window.confirm("Discard the unsaved editor draft?")) return;
    const remaining = allFiles.filter(f => f !== file); setFiles(remaining);
    if (active === path) { setActive(remaining.filter(f => f.scratch || f.projectId === projectId).at(-1)?.path || ""); setSelection(null); }
    if (projectId) remember(remaining, projectId);
  };
  const save = async (targetProject = project, path = current?.path, file = current) => {
    if (!targetProject || !path || !file || path.startsWith("untitled:")) throw new Error("Choose a workspace and filename with Save As.");
    setSaving(true); setError("");
    try {
      const data = await api<{content: string; sha256: string}>(`/projects/${targetProject.id}/files/write`, {method: "POST", body: JSON.stringify({path, content: file.content, base_hash: !file.scratch && file.projectId === targetProject.id && file.path === path ? file.baseHash : undefined})});
      setFiles(items => {
        const buffer = items.find(f => same(f, file));
        const content = buffer && buffer.content !== file.content ? buffer.content : data.content;
        const next = [...items.filter(f => !same(f, file) && !(f.path === path && f.projectId === targetProject.id)), {path, projectId: targetProject.id, content, original: data.content, baseHash: data.sha256, language: languageFor(path)}];
        remember(next, targetProject.id); return next;
      });
      if (currentProject.current === targetProject.id) setActive(path); return data;
    } catch (e) { setError(errorMessage(e)); throw e; }
    finally { setSaving(false); }
  };
  const update = (content: string) => setFiles(items => items.map(f => current && same(f, current) ? {...f, content, language: f.scratch && f.language === "plaintext" ? languageFor(f.path, content) : f.language} : f));
  const refreshSaved = async () => {
    if (!projectId) return;
    const clean = filesRef.current.filter(file => file.projectId === projectId && !file.scratch && file.content === file.original);
    await Promise.allSettled(clean.map(async file => {
      const data = await api<{content: string; sha256: string}>(`/projects/${projectId}/file?path=${encodeURIComponent(file.path)}`);
      setFiles(items => items.map(item => same(item, file) && item.content === item.original ? {...item, content: data.content, original: data.content, baseHash: data.sha256} : item));
    }));
    setSelection(null);
  };
  return {files, active, line, selection, setSelection, loading, saving, error, open, close, newScratch, save, update, current, refreshSaved,
    setLanguage: (language: string) => setFiles(items => items.map(f => current && same(f, current) ? {...f, language} : f)),
    renamed: (oldPath: string, destination: string) => { setFiles(items => items.map(f => f.projectId === projectId && (f.path === oldPath || f.path.startsWith(oldPath + "/")) ? {...f, path: destination + f.path.slice(oldPath.length)} : f)); if (active === oldPath || active.startsWith(oldPath + "/")) setActive(destination + active.slice(oldPath.length)); },
    removed: (path: string) => { setFiles(items => items.filter(f => !(f.projectId === projectId && (f.path === path || f.path.startsWith(path + "/"))))); if (active === path || active.startsWith(path + "/")) setActive(""); },
    overview: () => { setActive(""); setSelection(null); }};
}
