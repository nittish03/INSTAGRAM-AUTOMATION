import { NextRequest, NextResponse } from "next/server";

const BASE_URL = process.env.BACKEND_BASE_URL || "http://127.0.0.1:8000";

function buildUrl(path: string[], search: string) {
  // Backward-compatible guard: old frontend builds may call /backend/csrf etc.
  const normalizedPath = path[0] === "api" ? path : ["api", ...path];
  const joined = normalizedPath.join("/");
  const normalized = joined.endsWith("/") ? joined : `${joined}/`;
  return `${BASE_URL}/${normalized}${search || ""}`;
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = buildUrl(path, req.nextUrl.search);
  const cookie = req.headers.get("cookie") || "";

  const backendRes = await fetch(target, {
    method: req.method,
    headers: {
      cookie,
      "content-type": req.headers.get("content-type") || "application/json",
      "x-csrftoken": req.headers.get("x-csrftoken") || "",
    },
    body: ["GET", "HEAD"].includes(req.method) ? undefined : await req.text(),
    redirect: "manual",
    cache: "no-store",
  });

  const contentType = backendRes.headers.get("content-type") || "application/json";
  const body = await backendRes.text();
  const response = new NextResponse(body, {
    status: backendRes.status,
    headers: {
      "content-type": contentType,
      // Never cache API proxy responses — browsers cache 301/308 redirects aggressively and break login.
      "cache-control":
        "private, no-store, no-cache, max-age=0, must-revalidate",
      pragma: "no-cache",
      expires: "0",
      vary: "Cookie",
    },
  });

  const headersAny = backendRes.headers as unknown as { getSetCookie?: () => string[] };
  const cookies = headersAny.getSetCookie ? headersAny.getSetCookie() : null;
  if (cookies && cookies.length) {
    for (const c of cookies) response.headers.append("set-cookie", c);
  } else {
    const single = backendRes.headers.get("set-cookie");
    if (single) response.headers.append("set-cookie", single);
  }
  return response;
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx);
}
export async function PUT(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx);
}
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx);
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, ctx);
}
