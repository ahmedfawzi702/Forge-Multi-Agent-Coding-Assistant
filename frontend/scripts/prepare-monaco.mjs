import { mkdir, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = resolve(root, "public/monaco");
if (output !== resolve(root, "public", "monaco")) throw new Error("Invalid generated asset directory");
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
// Bundle ESM so the patched DOMPurify override is included in the served editor.
// Copying Monaco's prebuilt AMD bundle would retain its embedded old dependency.
await build({
  entryPoints: [resolve(root, "node_modules/monaco-editor/esm/vs/editor/editor.main.js")],
  bundle: true, format: "iife", globalName: "forgeMonaco", minify: true,
  outfile: resolve(output, "editor.js"), loader: { ".ttf": "file" },
});
const sources = {
  editor: "editor/editor.worker.js", json: "language/json/json.worker.js",
  css: "language/css/css.worker.js", html: "language/html/html.worker.js",
  ts: "language/typescript/ts.worker.js",
};
await Promise.all(Object.entries(sources).map(([name, source]) => build({
  entryPoints: [resolve(root, "node_modules/monaco-editor/esm/vs", source)],
  bundle: true, format: "iife", minify: true, outfile: resolve(output, `${name}.worker.js`),
})));
console.log("Monaco ESM and workers ready (local assets, patched sanitizer).");
