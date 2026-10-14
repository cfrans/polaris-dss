const test = require("node:test");
const assert = require("node:assert/strict");
const {setConnection, formatClock} = require("../../web/ui.js");
const {recentSample, percentage} = require("../../web/server-metrics.js");

test("connection state never reports green for a failed, unconfigured or unavailable probe", () => {
  const element = {dataset: {service: "Zabbix"}, setAttribute(name, value) { this[name] = value; }};
  setConnection(element, "ok", "2026-10-13T20:00:00Z", 140);
  assert.equal(element.dataset.state, "ok");
  assert.match(element["aria-label"], /conectado.*verificado às.*140 ms/);
  for (const state of ["falha", "aviso", "nao_configurado", "unknown", "invalid"]) {
    setConnection(element, state);
    assert.notEqual(element.dataset.state, "ok");
    assert.doesNotMatch(element["aria-label"], /verificado às/);
  }
});

test("clock uses the requested local timezone and changes date at midnight", () => {
  const before = formatClock(new Date("2026-10-14T02:59:59Z"), "America/Sao_Paulo");
  const after = formatClock(new Date("2026-10-14T03:00:00Z"), "America/Sao_Paulo");
  assert.equal(before.time, "23:59:59");
  assert.equal(after.time, "00:00:00");
  assert.notEqual(before.date, after.date);
  assert.equal(after.zone, "America/Sao_Paulo");
});

test("resource gauges distinguish genuine zero from missing, stale and invalid samples", () => {
  const now = Date.parse("2026-10-13T22:00:00Z");
  const sample = {percentual: 0, coletado_em: "2026-10-13T21:59:00Z"};
  assert.equal(recentSample(sample, now), sample);
  for (const invalid of [null, {...sample, percentual: "0"}, {...sample, percentual: NaN},
    {...sample, percentual: 101}, {...sample, percentual: -1},
    {...sample, coletado_em: "2026-10-13T21:54:59Z"},
    {...sample, coletado_em: "2026-10-13T22:01:00Z"}, {...sample, coletado_em: "bad"}]) {
    assert.equal(recentSample(invalid, now), null);
  }
  assert.equal(percentage(12.3), "12,3%");
});
