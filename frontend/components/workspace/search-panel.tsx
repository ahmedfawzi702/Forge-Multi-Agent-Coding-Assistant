"use client";
import { useState } from "react";
import { Search } from "lucide-react";
import { api } from "@/services/api";
import { errorMessage } from "@/services/storage";
import type { Project } from "@/types";

export function SearchPanel({project, onSource}: {project: Project | null; onSource: (path: string, line?: number) => void}) {
  const [query, setQuery] = useState(""), [include, setInclude] = useState("*"), [exclude, setExclude] = useState("");
  const [hits, setHits] = useState<{file: string; line: number; column: number; text: string}[]>([]), [error, setError] = useState(""), [busy, setBusy] = useState(false), [searched, setSearched] = useState(false);
  return <div className="search-panel"><form className="dock-toolbar" onSubmit={async e => {e.preventDefault(); if (!project) return; setBusy(true); setError(""); try {const result = await api<{hits: typeof hits}>(`/projects/${project.id}/search?q=${encodeURIComponent(query)}&include=${encodeURIComponent(include)}&exclude=${encodeURIComponent(exclude)}`); setHits(result.hits); setSearched(true);} catch (err) {setError(errorMessage(err));} finally {setBusy(false);}}}><Search size={14} /><input aria-label="Search in files" placeholder="Search in files…" value={query} onChange={e => setQuery(e.target.value)} /><input aria-label="Include files" placeholder="Include: *.py" value={include} onChange={e => setInclude(e.target.value)} /><input aria-label="Exclude files" placeholder="Exclude pattern" value={exclude} onChange={e => setExclude(e.target.value)} /><button className="secondary-button" disabled={!project || !query || busy}>{busy ? "Searching…" : "Search"}</button></form>{error && <div className="inline-error">{error}</div>}<div className="search-hits">{hits.map((hit, index) => <button key={index} onClick={() => onSource(hit.file, hit.line)}><span>{hit.file}:{hit.line}:{hit.column}</span><code>{hit.text}</code></button>)}{searched && !hits.length && <p className="quiet-note">No matches found.</p>}{!searched && <p className="quiet-note">Search workspace text. Results include file, line and column.</p>}</div></div>;
}
