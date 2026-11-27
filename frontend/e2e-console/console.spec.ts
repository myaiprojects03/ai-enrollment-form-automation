import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

const ENGINE = process.env.ENGINE_URL ?? "http://localhost:8000";
const TOKEN = process.env.OPERATOR_TOKEN ?? "";
const EMAIL = process.env.CONSOLE_EMAIL ?? "";
const PASSWORD = process.env.CONSOLE_PASSWORD ?? "";
test.skip(!TOKEN || !EMAIL || !PASSWORD, "set OPERATOR_TOKEN, CONSOLE_EMAIL and CONSOLE_PASSWORD");

const tag = () => randomUUID().slice(0, 8);
const year = new Date().getUTCFullYear();

/** A record straight into the engine, as n8n or an upload would send it. */
async function seed(record: Record<string, unknown>, form = "riverside-enrollment"): Promise<{ enrollment_id: string; outcome: string }> {
  const res = await fetch(`${ENGINE}/api/enrollments`, {
    method: "POST", headers: { authorization: `Bearer ${TOKEN}`, "content-type": "application/json" },
    body: JSON.stringify({ target_form: form, source: "api", record }),
  });
  expect(res.ok).toBe(true);
  return res.json();
}

const student = (over: Record<string, unknown> = {}) => ({
  first_name: "Leo", last_name: "Grant", date_of_birth: `${year - 17}-02-03`, email: `leo.${tag()}@example.com`,
  phone: "07911 234567", guardian_name: "Hannah Grant", guardian_phone: "07400 234567", program: "web-development",
  start_term: "2027-09", study_mode: "full_time", address_line1: "3 Canal Wharf", city: "Leeds", postcode: "LS11 5PS",
  consent_terms: true, ...over,
});

async function signIn(page: Page) {
  await page.goto("/console");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("console-user")).toHaveText(EMAIL);
}

test("a wrong password is refused with a plain message", async ({ page }) => {
  await page.goto("/console/enrollments/ENR-ANYTHING");
  await expect(page).toHaveURL(/\/console\/login\?next=/);
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("login-error")).toHaveText("Wrong email or password.");
});

test("a reviewer fixes a blocked record, approves it, and it is submitted with screenshots", async ({ page }) => {
  const { enrollment_id, outcome } = await seed(student());   // the guardian's relationship is missing
  expect(outcome).toBe("BLOCKED");
  await signIn(page);
  await page.getByTestId("tab-blocked").click();
  await page.getByRole("link", { name: enrollment_id }).click();
  await expect(page.getByTestId("reasons")).toContainText("Relationship to student: not found in the source");
  await expect(page.getByTestId("approve-submit")).toBeDisabled();
  await expect(page.locator('[data-field="guardian_name"]')).toContainText("Required for under-18s");

  await page.getByLabel("Relationship to student").selectOption("parent");
  await page.getByTestId("save").click();
  await expect(page.getByTestId("outcome")).toHaveText("PASS");
  await expect(page.locator('[data-field="guardian_relationship"]')).toContainText("edited");

  await page.getByTestId("approve-submit").click();
  await expect(page.getByTestId("status")).toHaveText("Submitted", { timeout: 60_000 });
  await expect(page.getByTestId("confirmation-ref")).toHaveText(/^RVA-\d{4}-[A-Z2-9]{5}$/);
  await expect(page.getByTestId("toast")).toContainText("Submitted");
  const shot = page.getByTestId("screenshots").locator("img");
  await expect(shot).toBeVisible();
  expect(await shot.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(600);

  await page.getByTestId("side-runs").click();
  await expect(page.getByTestId("runs")).toContainText("web form: succeeded");
  await page.reload();   // the history as it stands now, including the screenshot just viewed
  await page.getByTestId("side-audit").click();
  const history = page.getByTestId("audit");
  for (const step of ["Edited fields by", "Submitted by", "Viewed a screenshot by"]) await expect(history).toContainText(`${step} ${EMAIL}`);
  // Waiting for the portal does not flood the history with views of personal data.
  expect(await history.getByText("Opened personal data").count()).toBeLessThan(8);
});

test("a club membership waits for sign-off, then goes through the portal API", async ({ page }) => {
  const soon = new Date(Date.now() + 10 * 86_400_000).toISOString().slice(0, 10);
  const { enrollment_id, outcome } = await seed({
    full_name: "Sofia Marin", email: `sofia.${tag()}@example.com`, phone: "07800 345678", date_of_birth: "1991-09-30",
    membership_type: "family", family_members: 4, start_date: soon, interests: ["swimming"], emergency_contact_name: "Dan Marin",
    emergency_contact_phone: "07900 456789", accept_terms: true,
  }, "harbour-membership");
  expect(outcome).toBe("PASS");
  await signIn(page);
  const row = page.getByTestId("queue-table").getByRole("row").filter({ hasText: enrollment_id });
  await expect(row).toContainText("asks for a person to approve every submission");
  await row.getByRole("link").click();
  await page.getByTestId("approve-submit").click();
  await expect(page.getByTestId("status")).toHaveText("Submitted", { timeout: 60_000 });
  await expect(page.getByTestId("confirmation-ref")).toHaveText(/^HSC-\d{6}$/);
  await page.getByTestId("side-runs").click();
  await expect(page.getByTestId("runs")).toContainText("portal API: succeeded");
  await page.getByTestId("side-audit").click();
  await expect(page.getByTestId("audit")).toContainText(`Approved by ${EMAIL}`);
  await page.getByRole("link", { name: "Run history" }).click();
  await page.getByLabel("Enrollment ID or portal reference").fill(enrollment_id);
  const run = page.getByTestId("runs-table").getByRole("row").filter({ hasText: enrollment_id });
  await expect(run).toContainText("succeeded");
  await expect(run).toContainText(/HSC-\d{6}/);
});

test("a reviewer rejects a record and the audit log shows who and why", async ({ page }) => {
  const { enrollment_id } = await seed(student({ consent_terms: false }));
  await signIn(page);
  await page.goto(`/console/enrollments/${enrollment_id}`);
  await page.getByRole("button", { name: "Reject" }).click();
  await page.getByLabel("Reason").fill("Applicant withdrew on the phone");
  await page.getByTestId("confirm-reject").click();
  await expect(page.getByTestId("status")).toHaveText("Rejected");
  await expect(page.getByRole("button", { name: "Approve & submit" })).toHaveCount(0);
  await page.getByRole("link", { name: "Audit log" }).click();
  const row = page.getByTestId("audit-table").getByRole("row").filter({ hasText: enrollment_id }).filter({ hasText: "Rejected" });
  await expect(row).toContainText("Applicant withdrew on the phone");
  await expect(row).toContainText(EMAIL);
});

test("a CSV dropped into the queue is mapped and counted", async ({ page }) => {
  await signIn(page);
  const csv = `Student Name,D.O.B,E-mail,Mobile No,Course,Intake,Mode,Address,Terms Accepted\nSam Patel,30/06/2002,sam.${tag()}@example.com,07915 678901,Graphic Design,Jan 2027,Full-time,"12 Woodhouse Lane, Leeds, LS2 9JT",Yes\n`;
  await page.getByTestId("upload-file").setInputFiles({ name: "export.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByTestId("intake-result")).toHaveText("1 record: 1 pass.");
});

test("no serious accessibility problems in the queue and the editor", async ({ page }) => {
  const { enrollment_id } = await seed(student());
  await signIn(page);
  const bad = async () => (await new AxeBuilder({ page }).analyze()).violations
    .filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.help}`);
  expect(await bad()).toEqual([]);
  await page.goto(`/console/enrollments/${enrollment_id}`);
  await expect(page.getByTestId("fields")).toBeVisible();
  expect(await bad()).toEqual([]);
});

test("the proxy only reaches console paths, and writes need the console header", async ({ page, request }) => {
  expect((await request.get("/api/console/engine/enrollments")).status()).toBe(401);   // no session
  await signIn(page);
  const api = page.context().request;
  expect((await api.get("/api/console/engine/enrollments/counts")).status()).toBe(200);
  expect((await api.post("/api/console/engine/webhooks/intake", { data: {} })).status()).toBe(404);
  expect((await api.post("/api/console/engine/intake/notes", { data: { target_form: "riverside-enrollment", text: "x" } })).status()).toBe(403);
});
