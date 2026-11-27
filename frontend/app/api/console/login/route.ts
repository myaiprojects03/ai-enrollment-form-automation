import { cookies } from "next/headers";
import { COOKIE, engineUrl, secureCookies } from "@/lib/console/server";

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body || typeof body.email !== "string" || typeof body.password !== "string") {
    return Response.json({ error: "Enter your email and password." }, { status: 400 });
  }
  let res: Response;
  try {
    res = await fetch(`${engineUrl()}/api/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-forwarded-for": req.headers.get("x-forwarded-for") ?? "" },
      body: JSON.stringify({ email: body.email, password: body.password }),
      cache: "no-store",
    });
  } catch {
    return Response.json({ error: "The engine is not reachable. Check that it is running." }, { status: 502 });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const message = res.status === 401 ? "Wrong email or password." : res.status === 429
      ? "Too many failed attempts. Wait 15 minutes and try again." : String(data.detail ?? "Sign-in failed.");
    return Response.json({ error: message }, { status: res.status });
  }
  (await cookies()).set(COOKIE, data.token, {
    httpOnly: true, sameSite: "strict", secure: secureCookies(), path: "/",
    expires: new Date(Number(data.expires_at) * 1000),
  });
  return Response.json({ email: data.email });
}
