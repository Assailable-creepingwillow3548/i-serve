/* selftest.js -- is calc.js still bench/roofline.py?
 *
 * Runs every row of site/data/golden.json through Roofline.whatIfPoint and
 * compares the result with what Python produced for the same inputs. Numbers
 * to a relative 1e-9 (the expressions are ported in the same order, so they are
 * usually bit-identical; the tolerance forgives a harmless reassociation),
 * strings exactly, nulls exactly. The one field compared loosely is `error`:
 * Python and JavaScript format the sentence differently, so only its presence
 * has to agree.
 *
 * Two hosts, one file. Under node it reads the JSON from disk and exits
 * non-zero on the first disagreement -- that is the CI step. In a browser it
 * reads window.GOLDEN and window.MODEL_DATA and returns a report the page shows
 * as a badge, so a reader can see the check ran on the numbers in front of them.
 */
(function (root) {
  "use strict";
  const isNode = typeof module === "object" && module.exports;
  const Roofline = isNode ? require("./calc.js") : root.Roofline;

  function close(a, b) {
    if (a === b) return true;
    if (typeof a !== "number" || typeof b !== "number") return false;
    const scale = Math.max(Math.abs(a), Math.abs(b), 1e-300);
    return Math.abs(a - b) / scale <= 1e-9;
  }

  function diff(expected, actual, path, out) {
    if (expected === null || typeof expected !== "object") {
      if (path.endsWith(".error") || path === "error") {
        if ((expected === null) !== (actual === null)) out.push(path + ": " + expected + " vs " + actual);
      } else if (!close(expected, actual)) {
        out.push(path + ": expected " + JSON.stringify(expected) + ", got " + JSON.stringify(actual));
      }
      return;
    }
    if (actual === null || typeof actual !== "object") { out.push(path + ": expected an object, got " + actual); return; }
    const keys = new Set(Object.keys(expected).concat(Object.keys(actual)));
    for (const k of keys) diff(expected[k], actual[k], path ? path + "." + k : k, out);
  }

  function run(data, golden) {
    const failures = [];
    for (const row of golden) {
      let actual;
      try { actual = Roofline.whatIfPoint(data, row.inputs); }
      catch (e) { failures.push({ inputs: row.inputs, problems: ["threw: " + e.message] }); continue; }
      const problems = [];
      diff(row.expected, actual, "", problems);
      if (problems.length) failures.push({ inputs: row.inputs, problems });
    }
    return { rows: golden.length, failures };
  }

  if (isNode) {
    const fs = require("fs"), path = require("path");
    const here = __dirname;
    const data = JSON.parse(fs.readFileSync(path.join(here, "data", "model.json"), "utf8"));
    const golden = JSON.parse(fs.readFileSync(path.join(here, "data", "golden.json"), "utf8"));
    const report = run(data, golden);
    if (report.failures.length) {
      for (const f of report.failures.slice(0, 5)) {
        console.error("row " + JSON.stringify(f.inputs));
        for (const p of f.problems.slice(0, 5)) console.error("  " + p);
      }
      console.error("golden: " + (report.rows - report.failures.length) + "/" + report.rows + " rows agree");
      process.exit(1);
    }
    console.log("golden: " + report.rows + "/" + report.rows + " rows agree with bench/predictions.py");
  } else {
    root.Selftest = { run };
  }
})(typeof self !== "undefined" ? self : this);
