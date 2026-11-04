import { build } from "esbuild";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const output = resolve(".next/unit/project-source.mjs");
await mkdir(resolve(".next/unit"), { recursive: true });
await build({ entryPoints: ["services/project-source.ts"], outfile: output, bundle: true, format: "esm", platform: "node" });
const { allowedSnapshotPath, BrowserDirectoryProvider, LocalPathProvider } = await import(pathToFileURL(output).href);
for (const path of ["src/app.py", "app/page.tsx", "README.md", ".gitignore"]) assert.ok(allowedSnapshotPath(path), path);
for (const path of ["../secret.py", ".env", ".env.local", "private.pem", ".git/config", "node_modules/a.js", "C:/a.py", "a//b.py", "app/credentials.json"]) assert.equal(allowedSnapshotPath(path), false, path);
assert.deepEqual(await new LocalPathProvider("  /allowed/path  ").select(), { kind: "local", path: "/allowed/path" });
let pickerOptions;
globalThis.window = { showDirectoryPicker: async options => {
  pickerOptions = options;
  return { kind: "directory", name: "sample", async *values() {
    yield { kind: "file", name: "main.py", getFile: async () => new File(["def add(a,b): return a+b"], "main.py") };
    yield { kind: "file", name: ".env", getFile: async () => { throw Error("Sensitive file must never be read"); } };
    yield { kind: "directory", name: "node_modules", async *values() { throw Error("Excluded folder must not be traversed"); } };
  }};
}};
const source = await new BrowserDirectoryProvider(async () => null).select();
assert.equal(pickerOptions.mode, "read");
assert.equal(source.files.length, 1);
assert.equal(source.files[0].path, "main.py");
assert.equal(source.skipped, 2);
window.showDirectoryPicker = async () => { throw new DOMException("Cancelled", "AbortError"); };
assert.equal(await new BrowserDirectoryProvider(async () => null).select(), null);
window.showDirectoryPicker = async () => { throw new DOMException("Denied", "NotAllowedError"); };
await assert.rejects(() => new BrowserDirectoryProvider(async () => null).select(), /not granted/);
delete window.showDirectoryPicker;
const fallbackFile = new File(["value=1"], "app.py");
Object.defineProperty(fallbackFile, "webkitRelativePath", { value: "project/app.py" });
const fallback = await new BrowserDirectoryProvider(async () => [fallbackFile]).select();
assert.equal(fallback.name, "project"); assert.equal(fallback.files[0].path, "app.py");
console.log("Folder source unit checks passed: filtering, read-only picker, cancellation, permission errors, upload fallback.");

await build({entryPoints: ["chat/paused-task-card.tsx", "chat/tool-result-card.tsx"], outdir: resolve(".next/unit/lifecycle"),
  bundle: true, format: "esm", platform: "node", external: ["react", "react/jsx-runtime", "lucide-react"], jsx: "automatic", outExtension: {".js": ".mjs"}});
const React = await import("react");
const {renderToStaticMarkup} = await import("react-dom/server");
const {PausedTaskCard} = await import(pathToFileURL(resolve(".next/unit/lifecycle/paused-task-card.mjs")).href);
const paused = renderToStaticMarkup(React.createElement(PausedTaskCard, {result: {
  status: "paused", task_status: "PAUSED", stage: "IMPLEMENT", pause_reason: "PROVIDER_RATE_LIMIT",
  implementation_complete: false, staged_changes: {files: 2, directories: 5, applied_files: 0}, change_id: "fixture",
  model_selection: {automatic_fallback: false},
}, busy: false, onResume() {}, onCancel() {}, onDiff() {}}));
for (const label of ["Task paused safely", "Staged files", "Staged directories", "Applied files", "NOT RUN", "Resume", "Switch model", "Review staged changes", "Cancel task", "OFF"]) assert.ok(paused.includes(label), label);
assert.ok(!paused.includes("failed") && !paused.includes("/10"));
const {ToolResultCard} = await import(pathToFileURL(resolve(".next/unit/lifecycle/tool-result-card.mjs")).href);
const notRun = renderToStaticMarkup(React.createElement(ToolResultCard, {result: {type: "review", title: "Final review", status: "not_run", data: {status: "not_run", reason: "Implementation incomplete"}}, onSource() {}, onDiff() {}}));
assert.ok(!notRun.includes("Score") && !notRun.includes("gate did not pass"));
console.log("Lifecycle UI checks passed: paused controls, staged counts, NOT RUN gates and no fabricated review score.");
