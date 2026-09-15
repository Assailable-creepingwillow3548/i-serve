/* advisor.js -- walk docs/symptom-map.json as rules over the dashboard's readings.
 *
 * The knowledge is in the JSON, not here: this file knows how to evaluate a
 * predicate and how to walk a symptom's nodes in order, and nothing about
 * TTFT or KV caches. Every sentence it shows is a line of docs/symptom-map.md,
 * copied into the JSON and held equal to the markdown by a test.
 *
 * Three-valued logic, deliberately. A reading the reader marked "No data" is
 * null, and a clause over null is UNKNOWN, not false: on `kind` the stub
 * exports no histogram, so every branch that needs a p99 is unknowable there,
 * and the honest output is "cannot say, here is what it would need", never a
 * verdict invented from a blank. `all` with any false is false, else any
 * unknown is unknown; `any` with any true is true, else any unknown is
 * unknown. An empty `all` is true -- the "always" branch.
 */
(function (root) {
  "use strict";
  const UNKNOWN = "unknown";

  function value(clauseValue, readings) {
    if (clauseValue !== null && typeof clauseValue === "object" && "field" in clauseValue) {
      return readings[clauseValue.field];
    }
    return clauseValue;
  }

  function clause(c, readings) {
    const left = readings[c.field];
    if (c.op === "is_null") return left === null || left === undefined;
    if (c.op === "not_null") return !(left === null || left === undefined);
    const right = value(c.value, readings);
    if (left === null || left === undefined || right === null || right === undefined) return UNKNOWN;
    switch (c.op) {
      case "gt": return left > right;
      case "gte": return left >= right;
      case "lt": return left < right;
      case "lte": return left <= right;
      case "eq": return left === right;
      case "ne": return left !== right;
      default: throw new Error("unknown op " + c.op);
    }
  }

  function predicate(pred, readings) {
    if (!pred) return true;
    if (pred.all) {
      let unknown = false;
      for (const c of pred.all) {
        const r = clause(c, readings);
        if (r === false) return false;
        if (r === UNKNOWN) unknown = true;
      }
      return unknown ? UNKNOWN : true;
    }
    if (pred.any) {
      let unknown = false;
      for (const c of pred.any) {
        const r = clause(c, readings);
        if (r === true) return true;
        if (r === UNKNOWN) unknown = true;
      }
      return unknown ? UNKNOWN : false;
    }
    return true;
  }

  function missing(fields, readings) {
    return (fields || []).filter((f) => readings[f] === null || readings[f] === undefined);
  }

  function fieldsOf(pred) {
    const out = [];
    for (const c of (pred && (pred.all || pred.any)) || []) {
      out.push(c.field);
      if (c.value && typeof c.value === "object" && c.value.field) out.push(c.value.field);
    }
    return out;
  }

  function evaluate(map, readings) {
    const report = { active: [], inactive: [], unknown: [] };
    for (const symptom of map.symptoms) {
      const nodes = map.nodes.filter((n) => n.symptom === symptom.id);
      const state = predicate(symptom.active_when, readings);
      if (state === false) { report.inactive.push({ symptom }); continue; }
      if (state === UNKNOWN) {
        report.unknown.push({ symptom, missing: missing(fieldsOf(symptom.active_when), readings) });
        continue;
      }
      const entry = { symptom, probes: [], branch: null, continuations: [], traps: [], notEvaluable: [] };
      for (const n of nodes) {
        if (n.kind === "probe") entry.probes.push(n);
      }
      for (const n of nodes) {
        if (n.kind !== "branch" || entry.branch) continue;
        const need = missing(n.requires, readings);
        const r = need.length ? UNKNOWN : predicate(n.when, readings);
        if (r === true) entry.branch = n;
        else if (r === UNKNOWN) entry.notEvaluable.push({ node: n, missing: need.length ? need : missing(fieldsOf(n.when), readings) });
      }
      if (entry.branch) {
        entry.continuations = nodes.filter((n) => n.kind === "continuation" && n.parent === entry.branch.id);
      }
      for (const n of nodes) {
        if (n.kind !== "trap") continue;
        const need = missing(n.requires, readings);
        const r = need.length ? UNKNOWN : predicate(n.when, readings);
        if (r === true) entry.traps.push(n);
        else if (r === UNKNOWN) entry.notEvaluable.push({ node: n, missing: need.length ? need : missing(fieldsOf(n.when), readings) });
      }
      report.active.push(entry);
    }
    return report;
  }

  root.Advisor = { evaluate, predicate, UNKNOWN };
})(typeof self !== "undefined" ? self : this);
