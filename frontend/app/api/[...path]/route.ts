import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const origin = request.headers.get("origin");
  // Next may normalize nextUrl to its internal localhost origin even when the
  // browser used 127.0.0.1. Compare against the validated incoming Host instead.
  const host = request.headers.get("host") || "";
  let hostname: string;
  try { hostname = new URL(`http://${host}`).hostname; }
  catch { return Response.json({ detail: "Invalid host" }, { status: 400 }); }
  if (origin && origin !== `${request.nextUrl.protocol}//${host}`) {
    return Response.json({ detail: "Browser origin is not allowed" }, { status: 403 });
  }
  if (!["localhost", "127.0.0.1", "[::1]"].includes(hostname)) {
    return Response.json({ detail: "Local hosts only" }, { status: 403 });
  }
  const { path } = await context.params;
  if (!path.length || path.some(part => part === ".." || part.includes("/") || part.includes("\\"))) {
    return Response.json({ detail: "Invalid API path" }, { status: 400 });
  }
  const base = process.env.FORGE_BACKEND_URL || "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${base}/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`, {
      method: request.method,
      headers: { "Content-Type": "application/json" },
      body: request.method === "GET" ? undefined : await request.text(),
      signal: request.signal,
      cache: "no-store",
      redirect: "error",
    });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("Content-Type") || "application/json",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
      },
    });
  } catch {
    return Response.json({ detail: "Backend unavailable. Start FastAPI on 127.0.0.1:8000." }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST };
