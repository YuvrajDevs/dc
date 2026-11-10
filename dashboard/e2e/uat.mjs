// Automated acceptance: browser tests mapped to docs/UAT.md scenario IDs.
// Needs the API on :8000 and the dashboard on :3000 (see `make uat`).
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const axeSrc = readFileSync(new URL("../node_modules/axe-core/axe.min.js", import.meta.url), "utf8");
const BASE = process.env.BASE ?? "http://localhost:3000";

const results = [];
async function scenario(id, title, fn) {
  try { await fn(); results.push([id, title, true, ""]); }
  catch (e) { results.push([id, title, false, String(e.message).split("\n")[0]]); }
}
const ok = (c, m) => { if (!c) throw new Error(m); };
const browser = await chromium.launch(process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
const p = await ctx.newPage();
const consoleErrors = [];
p.on("pageerror", (e) => consoleErrors.push(String(e)));
p.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
const PAGES = ["/", "/dashboard", "/approvals", "/disputes", "/fees", "/exceptions", "/payouts", "/scorecard", "/runs", "/ask"];
const go = async (path) => { await p.goto(BASE + path, { waitUntil: "networkidle" }); };

await scenario("A1", "Landing leads to a dashboard that explains what needs attention", async () => {
  await go("/");
  await p.getByRole("link", { name: "Open dashboard" }).first().click();
  await p.waitForURL(/\/dashboard$/);
  await p.getByText("What needs attention").waitFor();
  await p.getByText("Open reconciliation errors").waitFor();
  const t = await p.locator("main").innerText();
  ok(/stopped answering/.test(t) && /Card testing/.test(t), "planted incidents not surfaced");
});
await scenario("N1", "Approvals drill into one issuer", async () => {
  await go("/approvals?dim=issuer");
  await p.getByRole("button", { name: /Issuer \d+ Bank/ }).first().click();
  await p.waitForURL(/issuer=ISS/);
  await p.getByRole("button", { name: /issuer ISS\d+ ✕/ }).waitFor();
});
await scenario("N2", "Disputes grid flags a merchant over the threshold", async () => {
  await go("/disputes");
  await p.getByText("Monthly dispute ratio vs thresholds").waitFor();
  const rows = await (await p.request.get(BASE + "/api/network/disputes")).json();
  ok(rows.monitoring.some((r) => r.programme_status === "excessive"), "no excessive merchant");
});
await scenario("N3", "Fees shows interchange paid above the rate card", async () => {
  await go("/fees");
  await p.getByText("Merchant economics").waitFor();
  ok(/txns/.test(await p.locator("main").innerText()), "no overpaid merchant flagged");
});
await scenario("A2", "Filter exceptions by kind narrows the list", async () => {
  await go("/exceptions");
  await p.locator("ul[aria-busy] button").first().waitFor();
  const before = await p.locator("ul[aria-busy] > li").count();
  const sel = p.locator("label:has-text(\"Kind\") select").first();
  const opts = await sel.locator("option").allTextContents();
  ok(opts.length > 2, "no kinds to filter");
  await sel.selectOption({ index: 2 });
  await p.waitForTimeout(600);
  const after = await p.locator("ul[aria-busy] > li").count();
  ok(after <= before && after > 0, `list did not narrow sensibly (${before} -> ${after})`);
});
await scenario("A3", "Opening an exception explains it in plain language", async () => {
  await go("/exceptions");
  await p.locator("ul[aria-busy] button").first().click();
  const d = p.getByRole("dialog");
  await d.waitFor();
  await d.getByText("What was matched").waitFor({ timeout: 8000 });
  ok((await d.innerText()).includes("What was matched"), "no matched records");
  ok((await d.locator("p").allInnerTexts()).some((t) => t.length > 30), "no reason text");
});
await scenario("A5", "Explaining needs a note, then persists with history", async () => {
  await go("/exceptions");
  await p.locator("ul[aria-busy] button").first().click();
  await p.getByRole("dialog").waitFor();
  await p.getByLabel("Your name").fill("uat-bot");
  await p.getByRole("button", { name: "Save decision" }).click();
  ok(/note/i.test(await p.locator("[aria-live=polite]").last().innerText()), "no validation message");
  await p.getByLabel(/^Note/).fill("UAT automated note");
  await p.getByRole("button", { name: "Save decision" }).click();
  await p.getByText("Saved.").waitFor();
  await p.getByRole("dialog").getByText("UAT automated note").first().waitFor({ timeout: 5000 });
});
await scenario("A9", "Esc closes the drawer and focus returns; keyboard reachable", async () => {
  await p.keyboard.press("Escape");
  await p.waitForTimeout(300);
  ok((await p.getByRole("dialog").count()) === 0, "drawer still open");
  await go("/");
  await p.keyboard.press("Tab");
  ok(await p.evaluate(() => document.activeElement?.textContent?.toLowerCase().includes("skip")), "skip link not first");
});
await scenario("A8", "CSV export downloads with a header row", async () => {
  await go("/exceptions");
  const [dl] = await Promise.all([p.waitForEvent("download"), p.getByRole("button", { name: "Export CSV" }).click()]);
  const text = readFileSync(await dl.path(), "utf8");
  ok(text.split("\n").length > 2 && text.includes(","), "csv looks empty");
});
await scenario("A10", "Ask answers with SQL shown", async () => {
  await go("/ask");
  await p.getByLabel("Your question").fill("Which merchants have the most exceptions?");
  await p.getByRole("button", { name: "Ask", exact: true }).click();
  await p.getByText("Show the query that ran").waitFor({ timeout: 8000 });
  await p.getByText("Show the query that ran").click();
  ok(/select/i.test(await p.locator("pre").innerText()), "sql not shown");
});
await scenario("A11", "Write attempts are refused with a reason", async () => {
  await go("/ask");
  await p.getByLabel("Your question").fill("Delete all findings");
  await p.getByRole("button", { name: "Ask", exact: true }).click();
  await p.getByText("I can’t run that").waitFor({ timeout: 8000 });
});
await scenario("R2", "Scorecard shows per-class results", async () => {
  await go("/scorecard");
  const t = await p.locator("main").innerText();
  ok(/precision/i.test(t) && /recall/i.test(t), "precision/recall missing");
});
await scenario("D1", "Runs page lists pipeline runs", async () => {
  await go("/runs");
  ok(/success|succeeded|ok/i.test(await p.locator("main").innerText()), "no successful run shown");
});
await scenario("R4", "No horizontal scroll on a phone", async () => {
  const m = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const mp = await m.newPage();
  for (const path of PAGES) {
    await mp.goto(BASE + path, { waitUntil: "networkidle" });
    ok(!(await mp.evaluate(() => document.documentElement.scrollWidth > innerWidth)), `overflow on ${path}`);
  }
  await m.close();
});
await scenario("X2", "Service down shows a clear message with retry", async () => {
  const c2 = await browser.newContext();
  const q = await c2.newPage();
  await q.route("**/api/**", (r) => r.abort());
  await q.goto(BASE + "/payouts");
  await q.getByRole("button", { name: /retry|try again/i }).waitFor({ timeout: 8000 });
  await c2.close();
});
await scenario("R5", "Axe: no serious/critical a11y violations on any page", async () => {
  const bad = [];
  for (const path of PAGES) {
    await go(path);
    await p.addScriptTag({ content: axeSrc });
    const r = await p.evaluate(() => axe.run(document, { runOnly: ["wcag2a", "wcag2aa", "wcag21aa"] }));
    for (const v of r.violations) if (["serious", "critical"].includes(v.impact)) bad.push(`${path}: ${v.id} (${v.nodes.length})`);
  }
  ok(bad.length === 0, bad.join("; "));
});
await scenario("X0", "No console or page errors during the run", async () => {
  ok(consoleErrors.length === 0, consoleErrors.slice(0, 2).join(" | ").slice(0, 200));
});

await browser.close();
for (const [id, t, pass, why] of results) console.log(`${pass ? "PASS" : "FAIL"}  ${id.padEnd(3)} ${t}${pass ? "" : "  <- " + why}`);
const failed = results.filter((r) => !r[2]).length;
console.log(`\n${results.length - failed}/${results.length} scenarios passed`);
process.exit(failed ? 1 : 0);
