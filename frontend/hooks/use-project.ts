"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/services/api";
import { errorMessage, readStored, writeStored } from "@/services/storage";
import type { ProjectSource } from "@/services/project-source";
import type { Health, Project, RecentProject } from "@/types";

export function useProject() {
  const [project, setProject] = useState<Project | null>(null);
  const [recent, setRecent] = useState<RecentProject[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const generation = useRef(0);
  const loadedId = useRef<string | undefined>(undefined);
  const load = useCallback((loaded: Project) => {
    generation.current++; loadedId.current = loaded.id; setProject(loaded); writeStored("forge-project-v2", loaded.id); setError("");
  }, []);
  useEffect(() => {
    let mounted = true;
    const connect = async () => {
      try { const data = await api<Health>("/health"); if (mounted) { setHealth(data); setConnectionError(""); } }
      catch (e) { if (mounted) { setHealth(null); setConnectionError(errorMessage(e)); } }
    };
    void connect();
    void api<RecentProject[]>("/projects").then(async items => {
      if (!mounted) return; setRecent(items);
      const last = readStored<string | null>("forge-project-v2", null);
      if (last && items.some(p => p.id === last)) { const data = await api<Project>(`/projects/${last}`); if (mounted && generation.current === 0) load(data); }
    }).catch(() => {});
    const timer = setInterval(connect, 15000);
    return () => { mounted = false; clearInterval(timer); };
  }, [load]);
  const open = async (source: ProjectSource) => {
    if (opening) return; setOpening(true); setError("");
    try {
      const loaded = await api<Project>(source.kind === "browser" ? "/projects/import" : "/projects/open", {
        method: "POST", body: JSON.stringify(source.kind === "browser" ? { name: source.name, files: source.files } : { path: source.path }),
      });
      if (source.kind === "browser" && source.skipped) loaded.project_map.warnings.push(`${source.skipped} excluded folders or unsupported files were skipped before import.`);
      load(loaded); setRecent(await api<RecentProject[]>("/projects")); return loaded;
    } catch (e) { setError(errorMessage(e)); throw e; } finally { setOpening(false); }
  };
  const refresh = async (id = project?.id) => {
    if (!id || opening) return; setOpening(true);
    try { const data = await api<Project>(`/projects/${id}/refresh`, { method: "POST" }); if (loadedId.current === id) setProject(data); }
    catch (e) { setError(errorMessage(e)); } finally { setOpening(false); }
  };
  const reopen = async (id: string) => {
    setOpening(true);
    try { load(await api<Project>(`/projects/${id}/refresh`, { method: "POST" })); }
    catch (e) { setError(errorMessage(e)); throw e; } finally { setOpening(false); }
  };
  const create = async (body: {name: string; location?: string; template: string; url?: string}) => {
    setOpening(true); setError("");
    try {
      const data = await api<Project>(body.url ? "/projects/clone" : "/projects/new", {method: "POST", body: JSON.stringify(body)});
      load(data); setRecent(await api<RecentProject[]>("/projects")); return data;
    } catch (e) { setError(errorMessage(e)); throw e; } finally { setOpening(false); }
  };
  return { project, recent, health, opening, error, connectionError, open, refresh, reopen, create,
    close: () => { generation.current++; loadedId.current = undefined; setProject(null); writeStored("forge-project-v2", null); } };
}
