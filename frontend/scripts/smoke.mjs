import assert from "node:assert/strict";

const base = process.env.FORGE_SMOKE_URL || "http://127.0.0.1:3000";
const health = await fetch(`${base}/api/health`);
assert.equal(health.status, 200, "Backend proxy must be reachable");
assert.ok((await health.json()).capabilities.includes("approved_apply"));
const sameOrigin = await fetch(`${base}/api/projects/open`, {
  method: "POST", headers: { Origin: base, "Content-Type": "application/json" }, body: "{}",
});
assert.equal(sameOrigin.status, 422, "Same-origin request must reach backend validation");
const crossOrigin = await fetch(`${base}/api/projects/open`, {
  method: "POST", headers: { Origin: "https://untrusted.example", "Content-Type": "application/json" }, body: "{}",
});
assert.equal(crossOrigin.status, 403, "Cross-origin request must be rejected");
console.log("Proxy smoke checks passed: connectivity, same-origin POST, cross-origin rejection.");
