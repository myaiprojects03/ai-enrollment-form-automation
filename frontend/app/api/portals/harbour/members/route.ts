/** Harbour Sports Club's partner API: POST a member, or GET ?email= to look one up. Needs X-Portal-Key. */
import { createMember } from "@/lib/portals/harbour-handler";
import { byEmail, json, keyOk } from "@/lib/portals/server";

export async function POST(req: Request) {
  if (!keyOk(req)) return json({ error: "A valid X-Portal-Key header is required." }, 401);
  return createMember(req);
}

export async function GET(req: Request) {
  if (!keyOk(req)) return json({ error: "A valid X-Portal-Key header is required." }, 401);
  const email = new URL(req.url).searchParams.get("email") ?? "";
  if (!email) return json({ error: "Pass ?email=" }, 400);
  return json({ members: (await byEmail("harbour", email)).map(({ ref, data, created_at }) => ({ member_id: ref, joined_at: created_at, member: data })) });
}
