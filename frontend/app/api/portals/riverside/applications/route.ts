/** Riverside Academy: the application form posts here (public, like any web form). Lookup by email needs the key. */
import { str, todayUtc } from "@/lib/portals/common";
import { normaliseRiverside, validateRiverside } from "@/lib/portals/riverside";
import { beforeSave, byEmail, chaosOf, json, keyOk, readBody, save } from "@/lib/portals/server";

export async function POST(req: Request) {
  const body = await readBody(req);
  if (!body) return json({ error: "Send the application as a JSON object." }, 400);
  const errors = validateRiverside(body, todayUtc());
  if (errors.length) return json({ errors }, 422);
  const data = normaliseRiverside(body);
  const email = str(data.email);
  // One application per student, programme and term: a resend gets the first reference back.
  const same = (await byEmail("riverside", email)).find((r) => r.data.program === data.program && r.data.start_term === data.start_term);
  if (same) return json({ error: "An application for this programme and term already exists.", ref: same.ref }, 409);
  const chaos = chaosOf(req);
  const early = await beforeSave(chaos, email);
  if (early) return early;
  const row = await save("riverside", email, data);
  if (chaos === "lost") return json({ error: "Gateway timeout" }, 504);
  return json({ ref: row.ref, received_at: row.created_at, application: row.data }, 201);
}

export async function GET(req: Request) {
  if (!keyOk(req)) return json({ error: "A valid X-Portal-Key header is required." }, 401);
  const email = new URL(req.url).searchParams.get("email") ?? "";
  if (!email) return json({ error: "Pass ?email=" }, 400);
  return json({ applications: (await byEmail("riverside", email)).map(({ ref, data, created_at }) => ({ ref, created_at, application: data })) });
}
