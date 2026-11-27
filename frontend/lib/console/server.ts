/** The console talks to the engine only from the server: the reviewer's session token lives in an httpOnly cookie
 * and never reaches the page's JavaScript. */
import "server-only";

export const COOKIE = "console_session";
export const engineUrl = () => (process.env.ENGINE_URL || "http://localhost:8000").replace(/\/$/, "");
export const secureCookies = () => process.env.NODE_ENV === "production";

/** Engine API paths the console may reach through the proxy. Anything else is refused. */
const ALLOWED = [/^auth\/me$/, /^forms$/, /^audit$/, /^enrollments(\/counts)?$/, /^enrollments\/ENR-[A-Z0-9]+(\/(fields|process|approve|reject|submit|runs|mapping))?$/,
  /^runs$/, /^runs\/[0-9a-f-]{36}\/screenshots\/\d+$/, /^intake\/(upload|notes)$/];
export const allowed = (path: string) => ALLOWED.some((re) => re.test(path));
