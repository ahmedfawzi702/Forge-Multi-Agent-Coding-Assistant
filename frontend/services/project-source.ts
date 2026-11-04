export type SnapshotFile = { path: string; content: string };
export type ProjectSource = { kind: "local"; path: string } | { kind: "browser"; name: string; files: SnapshotFile[]; skipped: number };
export interface ProjectSourceProvider { select(): Promise<ProjectSource | null> }
type FileHandle = { kind: "file"; name: string; getFile(): Promise<File> };
type DirectoryHandle = { kind: "directory"; name: string; values(): AsyncIterable<FileHandle | DirectoryHandle> };
type PickerWindow = { showDirectoryPicker?: (options: { mode: "read"; id: string }) => Promise<DirectoryHandle> };
const excluded = new Set([".git", ".svn", ".hg", "node_modules", ".venv", "venv", "env", ".next", ".data", "__pycache__", "dist", "build", "coverage"]);
const sensitive = new Set([".env", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519", "credentials", "credentials.json", "secrets.json", "secrets.yaml", "secrets.yml", "terraform.tfstate", "package-lock.json", "uv.lock", "pnpm-lock.yaml", "yarn.lock"]);
const supported = /\.(py|ts|tsx|js|jsx|mjs|cjs|json|md|toml|yaml|yml|css|html|txt|sql|rs|go|java|sh|ini|cfg|xml|cs|c|cpp)$/i;

export function allowedSnapshotPath(path: string): boolean {
  const parts = path.replaceAll("\\", "/").split("/");
  const name = parts.at(-1)?.toLowerCase() || "";
  return !/[:\x00-\x1f]/.test(path) && !parts.some(p => !p || p === "." || p === "..")
    && !parts.slice(0, -1).some(p => excluded.has(p.toLowerCase()) || p.startsWith("."))
    && !sensitive.has(name) && !name.startsWith(".env") && !/\.(pem|key|p12|pfx|db|sqlite)$/i.test(name)
    && (supported.test(name) || [".gitignore", "makefile", "dockerfile"].includes(name));
}

export class BrowserDirectoryProvider implements ProjectSourceProvider {
  constructor(private fallback: () => Promise<File[] | null>, private alternate = false) {}
  async select(): Promise<ProjectSource | null> {
    let skipped = 0, total = 0;
    const files: SnapshotFile[] = [];
    const add = async (file: File, path: string) => {
      if (!allowedSnapshotPath(path) || file.size > 262144) { skipped++; return; }
      if (files.length >= 3000 || total + file.size > 20 * 1024 * 1024) throw new Error("Folder exceeds the 3,000-file / 20 MB snapshot limit. Select a smaller folder.");
      let content: string;
      try { content = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer()); }
      catch { skipped++; return; }
      if (content.includes("\0")) { skipped++; return; }
      total += file.size; files.push({ path, content });
    };
    try {
      const picker = this.alternate ? undefined : (window as unknown as PickerWindow).showDirectoryPicker;
      let name: string;
      if (picker) {
        const root = await picker.call(window, { mode: "read", id: "forge-project" }); name = root.name;
        const walk = async (directory: DirectoryHandle, prefix = "") => {
          for await (const entry of directory.values()) {
            const path = prefix + entry.name;
            if (entry.kind === "directory") {
              if (excluded.has(entry.name.toLowerCase()) || entry.name.startsWith(".")) { skipped++; continue; }
              await walk(entry, path + "/");
            } else if (allowedSnapshotPath(path)) await add(await entry.getFile(), path);
            else skipped++;
          }
        };
        await walk(root);
      } else {
        const chosen = await this.fallback(); if (!chosen?.length) return null;
        name = chosen[0].webkitRelativePath.split("/")[0] || "Imported project";
        for (const file of chosen) await add(file, file.webkitRelativePath.split("/").slice(1).join("/") || file.name);
      }
      return { kind: "browser", name, files, skipped };
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return null;
      if (error instanceof DOMException && ["SecurityError", "NotAllowedError"].includes(error.name)) throw new Error("Folder access was not granted. Try the alternate picker or enter an allowed path manually.");
      throw error;
    }
  }
}
export class LocalPathProvider implements ProjectSourceProvider {
  constructor(private path: string) {}
  async select(): Promise<ProjectSource> { return { kind: "local", path: this.path.trim() }; }
}
export interface DesktopProjectSourceProvider extends ProjectSourceProvider { readonly host: "desktop" }
