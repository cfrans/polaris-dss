const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const history = require("../../web/decision-history.js");

function data(period = "7d", approved = 2, rejected = 1) {
  return {periodo: period, inicio: "2026-10-07T12:30:00Z", fim: "2026-10-14T12:30:00Z",
    fuso: "UTC", agrupamento: "day", totais: {aprovadas: approved, rejeitadas: rejected},
    series: [{inicio: "2026-10-07T00:00:00Z", aprovadas: approved, rejeitadas: rejected},
      {inicio: "2026-10-08T00:00:00Z", aprovadas: 0, rejeitadas: 0}]};
}

class Element {
  constructor(tag = "div") {
    this.tag = tag; this.children = []; this.attributes = {}; this.listeners = {}; this.value = "7d";
    const classes = new Set();
    this.classList = {add: name => classes.add(name), remove: name => classes.delete(name),
      contains: name => classes.has(name), toggle: (name, on) => on ? classes.add(name) : classes.delete(name)};
  }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || "") + this.children.map(child => child.textContent).join(""); }
  set innerHTML(_) { assert.fail("history must use literal text and SVG nodes"); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  appendChild(child) { this.children.push(child); }
  replaceChildren(...children) { this.children = children; this.text = ""; }
  addEventListener(event, listener) { this.listeners[event] = listener; }
}

function page(fetch) {
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const document = {hidden: false, getElementById: get, createElement: tag => new Element(tag),
    createElementNS: (_, tag) => new Element(tag), addEventListener() {}};
  const context = vm.createContext({window: {document}, fetch, AbortController, setTimeout, clearTimeout, setInterval() {}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../../web/decision-history.js"), "utf8"), context);
  return {get, document};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test("invalid or absent counts cannot become a healthy-looking zero; totals and dates must agree", () => {
  assert.equal(history.validateHistory(data(), "7d").totais.aprovadas, 2);
  for (const value of [null, NaN, -1, 1.5, "2"]) {
    const invalid = data(); invalid.series[0].aprovadas = value;
    assert.throws(() => history.validateHistory(invalid, "7d"));
  }
  const invalid = data(); invalid.totais.aprovadas = 3;
  assert.throws(() => history.validateHistory(invalid, "7d"));
  assert.throws(() => history.validateHistory(data("30d"), "7d"));
  assert.throws(() => history.validateHistory({...data(), fim: "invalid"}, "7d"));
  assert.equal(history.tickStep(1), 1);
  assert.equal(history.tickStep(9), 5);
  assert.match(history.bucketLabel("2026-10-14T00:15:00Z", "hour"), /14\/10.*00:15/);
});

test("operational decisions render with exact totals, SVG descriptions and a table without card writes", async () => {
  const calls = [];
  const {get} = page(async (...args) => { calls.push(args); return {ok: true, json: async () => data()}; });
  await settle();
  assert.equal(get("history-approved").textContent, "2");
  assert.equal(get("history-rejected").textContent, "1");
  const svg = get("history-chart").children[0];
  assert.equal(svg.tag, "svg");
  assert.match(svg.attributes["aria-label"], /2 aprovadas e 1 rejeitadas/);
  assert.equal(get("history-values").children.length, 2);
  assert.match(get("history-values").textContent, /07\/10/);
  assert.match(get("history-caption").textContent, /UTC.*parciais/);
  assert.deepEqual(calls.map(args => args[0]), ["/api/v1/historico-decisoes?period=7d"]);
  assert.equal(calls[0][1].method, undefined);
});

test("switching period rejects delayed older responses and failure clears obsolete chart and totals", async () => {
  let release;
  let fail = false;
  const {get} = page(url => {
    if (fail) return Promise.reject(new Error("offline"));
    if (url.endsWith("7d")) return new Promise(resolve => { release = resolve; });
    return Promise.resolve({ok: true, json: async () => data("30d", 4, 0)});
  });
  get("history-period").value = "30d";
  await get("history-period").listeners.change();
  release({ok: true, json: async () => data()});
  await settle();
  assert.equal(get("history-approved").textContent, "4");
  fail = true;
  await get("history-period").listeners.change();
  assert.equal(get("history-approved").textContent, "—");
  assert.equal(get("history-chart").children.length, 0);
  assert.equal(get("history-values").children.length, 0);
  assert.match(get("history-message").textContent, /Não foi possível/);
});

test("a successful empty period shows real zero totals and guidance rather than fake decisions", async () => {
  const {get} = page(async () => ({ok: true, json: async () => data("7d", 0, 0)}));
  await settle();
  assert.equal(get("history-approved").textContent, "0");
  assert.equal(get("history-rejected").textContent, "0");
  assert.equal(get("history-message").classList.contains("oculto"), false);
  assert.match(get("history-message").textContent, /Nenhuma aprovação/);
  assert.ok(get("history-chart").children.length);
});
