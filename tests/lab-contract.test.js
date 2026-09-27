import test from "node:test";
import assert from "node:assert/strict";
import {formatExact,formatPercent,safeRecordFilename,validatePointer,validateRecord} from "../apps/decision-lab/assets/contract.js";
import fs from "node:fs";
const pointer=JSON.parse(fs.readFileSync("exports/decision_lab/latest.json"));
const original=JSON.parse(fs.readFileSync(`exports/decision_lab/${pointer.path}`));
const clone=()=>structuredClone(original);

test("snapshot acceptance values and all methods remain artifact supplied",()=>{
  validatePointer(pointer); validateRecord(original,pointer);
  const values=Object.fromEntries(original.observations.map(o=>[o.capacity_definition_id,o.ratios.full_occupancy_idle_share_of_connected.value]));
  assert.equal(values.production,0.124428); assert.equal(values.robust_max_n1,0.11625);
  assert.equal(values.robust_max_n3,0.121787); assert.equal(values.robust_max_n10,0.124858);
  assert.equal(values.production,values.robust_max_n5);
  assert.equal(formatPercent(values.robust_max_n2),formatPercent(values.robust_max_n3));
});
test("null ratios are explicit while ordinary numeric zero remains zero",()=>{
  assert.equal(formatPercent(null),"Unavailable — denominator is zero");
  assert.equal(formatExact(0),"0"); assert.throws(()=>formatExact(undefined),/missing/);
});
test("semantic null states reject missing, falsy, and wrong statuses",()=>{
  for(const value of [undefined,"",0,false]){const r=clone();if(value===undefined)delete r.action.observed_action;else r.action.observed_action=value;assert.throws(()=>validateRecord(r,pointer),/Action/)}
  const outcome=clone();outcome.outcome.status="measured";assert.throws(()=>validateRecord(outcome,pointer),/Outcome/);
});
test("missing measurements, duplicates, unsupported schemas, and unsafe paths fail",()=>{
  const missing=clone();delete missing.observations[0].measures.idle_minutes.value;assert.throws(()=>validateRecord(missing,pointer),/required/);
  const duplicate=clone();duplicate.observations[1].capacity_definition_id="production";assert.throws(()=>validateRecord(duplicate,pointer),/unique/);
  const schema=clone();schema.schema_version="2.0.0";assert.throws(()=>validateRecord(schema,pointer),/Unsupported/);
  assert.throws(()=>safeRecordFilename("../record.json"),/allowed/); assert.throws(()=>safeRecordFilename("https://example.test/x.json"),/allowed/);
});
