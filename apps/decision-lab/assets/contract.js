export const SUPPORTED_IDS = ["production","robust_max_n1","robust_max_n2","robust_max_n3","robust_max_n5","robust_max_n10"];
export const METRICS = {
  idle_share_of_connected: "Post-charge idle share of connected time",
  full_occupancy_idle_share_of_connected: "Full-occupancy idle share of connected time",
  full_occupancy_share_of_idle: "Full-occupancy share of idle time"
};
const measures = ["connected_minutes","idle_minutes","full_occupancy_idle_minutes"];
const ratios = Object.keys(METRICS);
const own = (o,k) => Object.prototype.hasOwnProperty.call(o,k);
const object = (value,name) => { if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${name} is missing or invalid`); return value; };
const finite = (value,name) => { if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`${name} must be a finite number`); };

export function safeRecordFilename(path) {
  if (typeof path !== "string" || !/^[a-z0-9_]+-[a-f0-9]{16}\.json$/.test(path)) throw new Error("Pointer path is not an allowed local record filename");
  return path;
}
export function validatePointer(pointer) {
  object(pointer,"pointer");
  safeRecordFilename(pointer.path);
  if (pointer.decision_id !== "boulder_post_charge_idle_review" || typeof pointer.record_version !== "string" || `${pointer.record_version}.json` !== pointer.path) throw new Error("Pointer identity and filename do not agree");
  return pointer;
}
export function validateRecord(record,pointer) {
  object(record,"record");
  if (record.schema_version !== "1.0.0" || record.record_type !== "retrospective_analysis") throw new Error("Unsupported decision-record schema or type");
  if (record.decision_id !== pointer.decision_id || record.record_version !== pointer.record_version) throw new Error("Pointer and record identity do not agree");
  for (const key of ["population","evidence","recommendation","action","outcome"]) object(record[key],key);
  if (record.action.status !== "not_observed" || !own(record.action,"observed_action") || record.action.observed_action !== null) throw new Error("Action must be explicitly not_observed with a null value");
  if (record.outcome.status !== "not_measured" || !own(record.outcome,"measured_effect") || record.outcome.measured_effect !== null) throw new Error("Outcome must be explicitly not_measured with a null value");
  if (!Array.isArray(record.observations) || record.observations.length !== SUPPORTED_IDS.length) throw new Error("Exactly six supported observations are required");
  const ids = record.observations.map(o=>o.capacity_definition_id);
  if (new Set(ids).size !== ids.length || ids.some(id=>!SUPPORTED_IDS.includes(id)) || SUPPORTED_IDS.some(id=>!ids.includes(id))) throw new Error("Observation IDs must be unique and supported");
  for (const o of record.observations) {
    object(o.measures,`${o.capacity_definition_id}.measures`); object(o.ratios,`${o.capacity_definition_id}.ratios`);
    for (const id of measures) { const m=object(o.measures[id],id); if (!own(m,"value")) throw new Error(`${id}.value is required`); finite(m.value,`${id}.value`); }
    for (const id of ratios) { const ratio=object(o.ratios[id],id); if (!own(ratio,"value")) throw new Error(`${id}.value is required`); if (ratio.value !== null) finite(ratio.value,`${id}.value`); if (ratio.zero_denominator !== "null" || !measures.includes(ratio.numerator_metric_id) || !measures.includes(ratio.denominator_metric_id)) throw new Error(`${id} component contract is invalid`); }
  }
  return record;
}
export const formatPercent = value => value === null ? "Unavailable — denominator is zero" : `${(value*100).toFixed(1)}%`;
export const formatExact = value => { if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("Cannot format a missing measurement"); return String(value); };
export const formatMinutes = value => new Intl.NumberFormat("en-US",{maximumFractionDigits:3}).format(value);
export async function sha256Hex(bytes) { const digest=await crypto.subtle.digest("SHA-256",bytes); return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,"0")).join(""); }
