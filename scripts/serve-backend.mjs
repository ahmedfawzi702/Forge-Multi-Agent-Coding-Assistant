// Persistent local backend owner. Logs exits and restarts unexpected failures.
import {spawn} from "node:child_process";
import {appendFileSync, closeSync, mkdirSync, openSync, writeFileSync} from "node:fs";
import {dirname, resolve} from "node:path";
import {fileURLToPath} from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const state = resolve(root, ".data");
mkdirSync(state, {recursive: true});
const log = message => appendFileSync(resolve(state, "backend-supervisor.log"), `${new Date().toISOString()} ${message}\n`);
const python = process.platform === "win32" ? resolve(root, ".venv/Scripts/python.exe") : resolve(root, ".venv/bin/python");
let stopping = false, child, failures = 0, timer;

function start() {
  if (stopping) return;
  const output = openSync(resolve(state, "forge-api.stdout.log"), "a");
  const errors = openSync(resolve(state, "forge-api.stderr.log"), "a");
  const started = Date.now();
  child = spawn(python, ["-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8000"], {
    cwd: root, windowsHide: true, stdio: ["ignore", output, errors],
  });
  closeSync(output); closeSync(errors);
  writeFileSync(resolve(state, "backend-supervisor.json"), JSON.stringify({supervisor: process.pid, launcher: child.pid, started_at: new Date().toISOString()}, null, 2));
  log(`Started backend launcher pid=${child.pid}; supervisor pid=${process.pid}`);
  child.on("error", error => log(`Backend spawn failed: ${error.code || "unknown"}`));
  child.once("close", (code, signal) => {
    log(`Backend exited code=${code} signal=${signal || "none"} uptime_ms=${Date.now() - started}`);
    if (stopping) return;
    failures = Date.now() - started > 60000 ? 1 : failures + 1;
    if (failures >= 5) {
      log("Stopped after five consecutive short-lived failures. Inspect forge-api.stderr.log and relaunch.");
      process.exitCode = 1;
      return;
    }
    const delay = Math.min(30000, 1000 * 2 ** failures);
    log(`Restarting in ${delay}ms`);
    timer = setTimeout(start, delay);
  });
}

function stop() {
  if (stopping) return;
  stopping = true;
  clearTimeout(timer);
  log("Supervisor stopping");
  if (child?.pid && child.exitCode === null) {
    if (process.platform === "win32") {
      spawn("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {windowsHide: true, stdio: "ignore"});
    } else child.kill("SIGTERM");
  }
}
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
start();
