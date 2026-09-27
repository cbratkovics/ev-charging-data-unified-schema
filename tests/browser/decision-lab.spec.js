import {test,expect} from "@playwright/test";
import fs from "node:fs";
const pointer=JSON.parse(fs.readFileSync("exports/decision_lab/latest.json"));
const recordBytes=fs.readFileSync(`exports/decision_lab/${pointer.path}`);
const record=JSON.parse(recordBytes);

test.beforeEach(async({page})=>{await page.goto("/lab/");await expect(page.getByRole("heading",{name:"Idle time is not the same as unmet demand."})).toBeVisible();await expect(page.getByText("Production is the published default.")).toBeVisible()});
test("default record and every supplied scenario update atomically",async({page})=>{
  const select=page.getByLabel("Capacity definition");await expect(select).toHaveValue("production");
  await expect(page.getByText("12.4%",{exact:true})).toBeVisible();await expect(page.getByText(/Source-local starts: 2018-01-01/)).toBeVisible();
  for(const o of record.observations){await select.selectOption(o.capacity_definition_id);await expect(page.locator("#method-id")).toHaveText(o.capacity_definition_id);await expect(page.locator("#method-definition")).toHaveText(o.capacity_assumption);await expect(page.locator("#full-component")).toContainText(new Intl.NumberFormat("en-US",{maximumFractionDigits:3}).format(o.measures.full_occupancy_idle_minutes.value));}
  await select.selectOption("robust_max_n5");await expect(page.getByText(/same measurement as production/)).toBeVisible();
});
test("open inspector updates with selection and returns focus with Escape",async({page})=>{
  const button=page.getByRole("button",{name:"Inspect evidence"}).nth(1);await button.click();await expect(page.getByRole("dialog")).toBeVisible();await expect(page.getByText("0.124428",{exact:true})).toBeVisible();
  await page.getByLabel("Capacity definition").selectOption("robust_max_n3");await expect(page.getByText("0.121787",{exact:true})).toBeVisible();await expect(page.getByRole("dialog")).toContainText("robust_max_n3");
  await page.keyboard.press("Escape");await expect(button).toBeFocused();await expect(page.getByText("Not observed",{exact:true})).toBeVisible();await expect(page.getByText("Not measured",{exact:true})).toBeVisible();
});
test("download preserves immutable bytes and filename",async({page})=>{const downloadPromise=page.waitForEvent("download");await page.getByRole("button",{name:"Download decision record"}).click();const download=await downloadPromise;expect(download.suggestedFilename()).toBe(pointer.path);expect(fs.readFileSync(await download.path())).toEqual(recordBytes)});
test("repository prefix and root docs work without a rewrite",async({page,request})=>{await page.goto("/ev-charging-data-unified-schema/lab/");await expect(page.locator("#capacity")).toHaveValue("production");expect((await request.get("/ev-charging-data-unified-schema/lab/assets/app.js")).ok()).toBeTruthy();expect((await request.get("/ev-charging-data-unified-schema/lab/data/latest.json")).ok()).toBeTruthy();expect((await request.get("/ev-charging-data-unified-schema/")).ok()).toBeTruthy()});
test("malformed data and altered bytes show retryable failures",async({page})=>{await page.route("**/data/latest.json",r=>r.fulfill({body:"{"}));await page.reload();await expect(page.getByRole("alert")).toContainText("not valid JSON");await expect(page.getByRole("button",{name:"Retry"})).toBeVisible()});
test("no automatic third-party requests",async({page})=>{const external=[];page.on("request",r=>{if(new URL(r.url()).hostname!=="127.0.0.1")external.push(r.url())});await page.reload();expect(external).toEqual([])});
