/** Forwards the console's requests to the engine with the reviewer's session. Writes need the x-console header,
 * which a page on another site cannot send (with the strict same-site cookie, that stops cross-site requests). */
import { cookies } from "next/headers";
import { allowed, COOKIE, engineUrl } from "@/lib/console/server";

type Ctx = { params: Promise<{ path: string[] }> };

async function forward(req: Request, ctx: Ctx): Promise<Response> {
  const path = (await ctx.params).path.join("/");
  if (!allowed(path)) return Response.json({ detail: "Not available from the console." }, { status: 404 });
  if (req.method !== "GET" && req.headers.get("x-console") !== "1") {
    return Response.json({ detail: "Missing x-console header." }, { status: 403 });
  }
  const token = (await cookies()).get(COOKIE)?.value;
  if (!token) return Response.json({ detail: "Sign in again." }, { status: 401 });
  const url = `${engineUrl()}/api/${path}${new URL(req.url).search}`;
  const headers: Record<string, string> = { authorization: `Bearer ${token}` };
  const type = req.headers.get("content-type");
  if (type) headers["content-type"] = type;
  let res: Response;
  try {
    res = await fetch(url, {
      method: req.method, headers, cache: "no-store",
      body: req.method === "GET" ? undefined : await req.arrayBuffer(),
    });
  } catch {
    return Response.json({ detail: "The engine is not reachable." }, { status: 502 });
  }
  const out = new Headers({ "cache-control": "private, no-store" });
  const resType = res.headers.get("content-type");
  if (resType) out.set("content-type", resType);
  return new Response(res.body, { status: res.status, headers: out });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
