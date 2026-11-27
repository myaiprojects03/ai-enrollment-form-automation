import { expect, type Page, test } from "@playwright/test";
import { application, dobUk, email } from "./helpers";

const URL = "/portals/riverside/enroll";

async function student(page: Page, who: { dob: string; mail: string; phone?: string }) {
  await page.getByTestId("ra-first-name").fill("Amara");
  await page.getByTestId("ra-last-name").fill("Okafor");
  await page.getByTestId("ra-date-of-birth").fill(who.dob);
  await page.getByTestId("ra-email").fill(who.mail);
  await page.getByTestId("ra-phone").fill(who.phone ?? "07911 123456");
  await page.getByTestId("ra-next").click();
}

async function courseAndAddress(page: Page) {
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your course");
  await page.getByTestId("ra-program").fill("data");
  await page.getByTestId("ra-program-option-data-analytics").click();
  await expect(page.getByTestId("ra-program")).toHaveValue("Data Analytics (Level 4)");
  await page.getByTestId("ra-start-term-2027-04").check();
  await page.getByTestId("ra-study-mode").selectOption("part_time");
  await page.getByTestId("ra-next").click();
  await page.getByTestId("ra-address-line1").fill("14 Mill Lane");
  await page.getByTestId("ra-city").fill("Leeds");
  await page.getByTestId("ra-postcode").fill("ls1 4ap");
  await page.getByTestId("ra-next").click();
}

test("an adult applies in four steps and the guardian step is skipped", async ({ page }) => {
  const mail = email("amara");
  await page.goto(URL);
  await student(page, { dob: dobUk(28), mail });
  await expect(page.getByText("Not needed (18 or over)")).toBeVisible();
  await courseAndAddress(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Check your answers");
  await expect(page.getByTestId("ra-review-program")).toHaveText("Data Analytics (Level 4)");
  await page.getByTestId("ra-consent-terms").check();
  await page.getByTestId("ra-submit").click();
  await expect(page.getByTestId("ra-confirmation-ref")).toHaveText(/^RVA-\d{4}-[A-Z2-9]{5}$/);
  // Read-back: what the academy stored, normalised.
  await expect(page.getByTestId("ra-confirm-email")).toHaveText(mail);
  await expect(page.getByTestId("ra-confirm-phone")).toHaveText("+447911123456");
  await expect(page.getByTestId("ra-confirm-postcode")).toHaveText("LS1 4AP");
  await expect(page.getByTestId("ra-confirm-start-term")).toHaveAttribute("data-value", "2027-04");
});

test("a 16-year-old needs a guardian with a different number", async ({ page }) => {
  await page.goto(URL);
  await student(page, { dob: dobUk(16), mail: email("leo"), phone: "07911 234567" });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Parent or guardian");
  await page.getByTestId("ra-guardian-name").fill("Hannah Grant");
  await page.getByTestId("ra-guardian-relationship-parent").check();
  await page.getByTestId("ra-guardian-phone").fill("+44 7911 234567");
  await page.getByTestId("ra-next").click();
  await expect(page.getByTestId("ra-guardian-phone-error")).toContainText("different from the student's");
  await page.getByTestId("ra-guardian-phone").fill("07400 234567");
  await page.getByTestId("ra-next").click();
  await courseAndAddress(page);
  await expect(page.getByTestId("ra-review-guardian-name")).toHaveText("Hannah Grant");
  await page.getByTestId("ra-consent-terms").check();
  await page.getByTestId("ra-submit").click();
  await expect(page.getByTestId("ra-confirm-guardian-phone")).toHaveText("+447400234567");
});

test("empty step: an error summary takes focus and every field says what to fix", async ({ page }) => {
  await page.goto(URL);
  await page.getByTestId("ra-next").click();
  const summary = page.getByTestId("ra-error-summary");
  await expect(summary).toBeFocused();
  await expect(summary.getByRole("listitem")).toHaveCount(5);
  await expect(page.getByTestId("ra-email")).toHaveAttribute("aria-invalid", "true");
  await page.getByTestId("ra-date-of-birth").fill("31/02/2001");
  await page.getByTestId("ra-next").click();
  await expect(page.getByTestId("ra-date-of-birth-error")).toContainText("real date");
});

test("the calendar picks a date and the combobox works by keyboard", async ({ page }) => {
  await page.goto(URL);
  await page.getByTestId("ra-date-of-birth-calendar-button").click();
  const cal = page.getByTestId("ra-date-of-birth-calendar");
  await cal.getByLabel("Month").selectOption({ label: "March" });
  await cal.getByLabel("Year").selectOption("2000");
  await cal.getByRole("button", { name: "27 March 2000" }).click();
  await expect(page.getByTestId("ra-date-of-birth")).toHaveValue("27/03/2000");
  await page.getByTestId("ra-first-name").fill("Amara");
  await page.getByTestId("ra-last-name").fill("Okafor");
  await page.getByTestId("ra-email").fill(email("kb"));
  await page.getByTestId("ra-phone").fill("07911 123456");
  await page.getByTestId("ra-next").click();
  const combo = page.getByRole("combobox", { name: "Programme" });
  await combo.fill("sec");
  await combo.press("Enter");
  await expect(combo).toHaveValue("Cyber Security Essentials");
  await combo.fill("underwater basket weaving");
  await expect(page.getByText("No programme matches")).toBeVisible();
  await page.getByTestId("ra-next").click();
  await expect(page.getByTestId("ra-program-error")).toHaveText(/Choose a programme/);
});

test("variant b drifts (labels, order, no test ids) but stays usable by label", async ({ page }) => {
  await page.goto(`${URL}?variant=b`);
  await expect(page.locator("[data-testid]")).toHaveCount(0);
  await page.getByLabel("Given name").fill("Amara");
  await page.getByLabel("Family name").fill("Okafor");
  await page.getByLabel("Birth date").fill(dobUk(30));
  await page.getByLabel("Email", { exact: true }).fill(email("drift"));
  await page.getByLabel("Mobile phone").fill("07911 123456");
  await page.getByRole("button", { name: "Next step" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Home address");
  await page.getByLabel("House number and street").fill("2 Quay Street");
  await page.getByLabel("Town").fill("Bristol");
  await page.getByLabel("Post code").fill("BS1 4DJ");
  await page.getByRole("button", { name: "Next step" }).click();
  await page.getByRole("combobox", { name: "Course" }).fill("Accounting");
  await page.getByRole("option", { name: "Accounting (AAT Level 3)" }).click();
  await page.getByRole("radio", { name: "September 2027" }).check();
  await page.getByLabel("How will you study?").selectOption({ label: "Online" });
  await page.getByRole("button", { name: "Next step" }).click();
  await page.getByLabel("I accept the terms of enrollment").check();
  await page.getByRole("button", { name: "Send application" }).click();
  await expect(page.getByTestId("ra-confirmation-ref")).toBeVisible();
});

test("the same application twice returns the first reference", async ({ request }) => {
  const body = application();
  const first = await request.post("/api/portals/riverside/applications", { data: body });
  expect(first.status()).toBe(201);
  const again = await request.post("/api/portals/riverside/applications", { data: body });
  expect(again.status()).toBe(409);
  expect((await again.json()).ref).toBe((await first.json()).ref);
});

test("server-side validation reports fields, not just a status", async ({ request }) => {
  const res = await request.post("/api/portals/riverside/applications", {
    data: application({ program: "astrology", postcode: "NOPE", consent_terms: false, shoe_size: 9 }),
  });
  expect(res.status()).toBe(422);
  const fields = (await res.json()).errors.map((e: { field: string }) => e.field).sort();
  expect(fields).toEqual(["consent_terms", "postcode", "program", "shoe_size"]);
});

test("captcha mode shows a security check and blocks submission", async ({ page }) => {
  await page.goto(`${URL}?chaos=captcha`);
  await student(page, { dob: dobUk(30), mail: email("bot") });
  await courseAndAddress(page);
  await page.getByTestId("ra-consent-terms").check();
  await expect(page.getByTestId("captcha")).toBeVisible();
  await expect(page.getByTestId("ra-submit")).toBeDisabled();
});
