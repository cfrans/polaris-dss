const test = require("node:test");
const assert = require("node:assert/strict");
const {setConnection, setDisclosure, showDialog, closeDialog, formatClock} = require("../../web/ui.js");
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

test("disclosure state keeps its animated panel and keyboard access in sync", () => {
  const panel = {classes: new Set(), attributes: {}, classList: {
    toggle(name, active) { active ? this.owner.classes.add(name) : this.owner.classes.delete(name); },
  }, setAttribute(name, value) { this.attributes[name] = value; }};
  panel.classList.owner = panel;
  panel.querySelector = () => clip;
  const clip = {inert: true};
  const trigger = {attributes: {}, classes: new Set(), setAttribute(name, value) { this.attributes[name] = value; },
    classList: {toggle(name, active) { active ? trigger.classes.add(name) : trigger.classes.delete(name); }}};
  setDisclosure(panel, trigger, true);
  assert.equal(panel.classes.has("is-open"), true);
  assert.equal(panel.attributes["aria-hidden"], "false");
  assert.equal(clip.inert, false);
  assert.equal(trigger.attributes["aria-expanded"], "true");
  setDisclosure(panel, trigger, false);
  assert.equal(panel.classes.has("is-open"), false);
  assert.equal(panel.attributes["aria-hidden"], "true");
  assert.equal(clip.inert, true);
  assert.equal(trigger.attributes["aria-expanded"], "false");
});

test("modal helpers animate the close before dismissing the dialog", async t => {
  const previousFrame = globalThis.requestAnimationFrame;
  const previousMedia = globalThis.matchMedia;
  globalThis.requestAnimationFrame = callback => { callback(); return 1; };
  globalThis.matchMedia = () => ({matches: true});
  t.after(() => {
    if (previousFrame === undefined) delete globalThis.requestAnimationFrame;
    else globalThis.requestAnimationFrame = previousFrame;
    if (previousMedia === undefined) delete globalThis.matchMedia;
    else globalThis.matchMedia = previousMedia;
  });

  const classes = new Set();
  const dialog = {open: false, classList: {
    add: name => classes.add(name),
    remove: name => classes.delete(name),
    contains: name => classes.has(name),
  }, showModal() { this.open = true; }, close() { this.open = false; }};
  showDialog(dialog);
  assert.equal(dialog.open, true);
  assert.equal(classes.has("is-visible"), true);
  closeDialog(dialog);
  assert.equal(classes.has("is-closing"), true);
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(dialog.open, false);
  assert.equal(classes.has("is-closing"), false);
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
