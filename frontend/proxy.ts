import { NextResponse, type NextRequest } from "next/server";

/** Console pages need a session cookie; without one, go to sign-in. (The engine checks the token itself.) */
export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (pathname.startsWith("/console") && pathname !== "/console/login" && !req.cookies.get("console_session")) {
    const url = req.nextUrl.clone();
    url.pathname = "/console/login";
    url.search = pathname === "/console" ? "" : `?next=${encodeURIComponent(pathname)}`;
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/console/:path*"] };
