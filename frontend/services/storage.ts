export function readStored<T>(key: string, fallback: T): T {
  try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) as T : fallback; }
  catch { return fallback; }
}
export function writeStored(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Private mode or quota. */ }
}
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not complete.";
}
