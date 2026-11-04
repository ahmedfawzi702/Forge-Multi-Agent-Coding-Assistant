export type FileEntry = { path: string; language: string; size: number };
export type Evidence = { file: string; start_line: number; end_line: number; sha256: string };
export type Project = {
  id: string; name: string; path: string;
  source_kind?: "local" | "browser" | "managed"; permission?: string;
  project_map: {
    files: FileEntry[]; language: string[]; framework: string[];
    symbols: { name: string; type: string; file_path: string; start_line: number }[];
    warnings: string[]; architecture_summary: string; scanned_at: string;
    testing_framework?: string[]; database_layer?: string[];
    directories?: string[];
  };
};
export type Health = { provider: string; model: string | null; model_configured: boolean; read_only: boolean };
export type ChatMode = "auto" | "ask" | "plan";
export type ChatResult = {
  run_id: string; conversation_id: string; intent: string;
  status: "pending" | "running" | "paused" | "cancelled" | "completed" | "unsupported" | "failed" | "partial" | "proposed" | "awaiting_approval" | "blocked";
  answer: string; evidence: Evidence[]; confidence: string; provider: string;
  intents: string[]; artifacts: ToolResult[]; change_id?: string | null;
  diagnostics?: Record<string, unknown>; resumable?: boolean;
  task_status?: "PENDING" | "RUNNING" | "PAUSED" | "BLOCKED" | "COMPLETED" | "FAILED" | "CANCELLED";
  stage?: string; stage_states?: Record<string, string>; implementation_complete?: boolean;
  checkpoint_preserved?: boolean; staged_changes?: {files: number; directories: number; applied_files: number};
  pause_reason?: string | null; retryable?: boolean; retry_at?: string | null; retry_after_seconds?: number | null;
  tests?: Record<string, unknown>; security?: Record<string, unknown>; review?: Record<string, unknown>;
  model_selection?: {provider?: string; model?: string; active_model?: string; automatic_fallback?: boolean};
};
export type ChatMessage = { role: "user" | "assistant"; content: string; result?: ChatResult | null; events?: AgentEvent[] };
export type AgentEvent = { type: string; message: string; data: Record<string, unknown>; agent?: string | null; status?: string | null };
export type Activity = { message: string; state: "complete" | "active" | "error"; time: string };
export type ToolResult = { type: string; title: string; status: string; data: Record<string, unknown> };
export type SelectionContext = { file: string; start_line: number; end_line: number; start_column?: number; end_column?: number; text?: string; base_hash?: string };
export type OpenFile = { path: string; content: string; original: string; language: string; baseHash: string; scratch?: boolean; projectId?: string };
export type RecentProject = { id: string; name: string; path: string };
export type Problem = {file: string; line: number; column: number; severity: string; message: string; source: string};
export type ChangeFile = { path: string; before: string; after: string; reason: string; diff: string; additions: number; deletions: number; risk: string; applied: boolean; rejected?: boolean; delete?: boolean; directory?: boolean };
export type ChangeSet = { id: string; status: string; can_apply: boolean; proposal: {
  run_id?: string | null;
  summary: string; files: ChangeFile[]; source_kind?: "local" | "browser" | "managed";
  static: Record<string, unknown>; security: Record<string, unknown>;
  tests: Record<string, unknown>; review: Record<string, unknown>;
}};
