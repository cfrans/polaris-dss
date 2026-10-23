const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ui = require("../../web/ui.js");
const reconciliation = require("../../web/reconciliation.js");

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.value = "";
    this.hiddenClasses = new Set(["oculto"]);
    this.attributes = new Map();
    this.dataset = {};
    this.classList = {
      add: name => this.hiddenClasses.add(name),
      remove: name => this.hiddenClasses.delete(name),
      toggle: (name, enabled) => enabled ? this.hiddenClasses.add(name) : this.hiddenClasses.delete(name),
    };
  }
  set textContent(value) { this.value = String(value); this.children = []; }
  get textContent() { return this.value + this.children.map(child => child.textContent).join(""); }
  set innerHTML(value) {
    assert.equal(value, "", "dynamic activity/error text must never be interpreted as HTML");
    this.replaceChildren();
  }
  replaceChildren() { this.value = ""; this.children = []; }
  appendChild(child) { this.children.push(child); }
  setAttribute(name, value) { this.attributes.set(name, value); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  querySelector() { return this.clip ??= new Element(); }
  focus() { this.focused = true; }
}

function viewer(data) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const context = vm.createContext({
    $: get,
    document: {createElement: tag => new Element(tag), getElementById:get},
    window: {PolarisUI: ui, PolarisReconciliation:reconciliation},
    api: async route => {
      assert.equal(route, "/api/v1/reconciliacao");
      return data;
    },
  });
  const source = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8");
  const block = source.split("/* ---------- reconciliação ---------- */")[1]
    .split("/* ---------- lista ---------- */")[0];
  vm.runInContext(block, context);
  return {get, context};
}

const cycle = {status: "sucesso", ts_conclusao: "2026-10-13T20:00:00Z",
  recuperados: 1, ja_conhecidos: 2, encerrados_na_origem: 3, mensagem_erro: null};
const data = {status: "sucesso", habilitada: true, intervalo_segundos: 30,
  ultimo_ciclo: cycle, contagens_incidentes: {pendente: 0, sucesso: 3}, historico: []};

test("refresh preserves recorded activities, counts and literal error text without duplicating rows", async () => {
  const message = '<img src=x onerror="alert(1)">\n<script>test</script>';
  const recorded = [cycle, {...cycle, status: "erro", mensagem_erro: message}];
  const {get, context} = viewer({...data, historico: recorded});
  await context.carregarReconciliacao();
  await context.carregarReconciliacao();
  const history = get("recon-historico");
  assert.equal(history.children.length, 2);
  assert.equal(get("recon-history-count").textContent, "2");
  assert.equal(history.children[0].children[1].textContent, "OK");
  const error = history.children[1];
  assert.equal(error.children[1].textContent, "ERRO");
  assert.equal(error.children[2].textContent,
    message + "\n1 recuperado(s), 2 conhecido(s), 3 encerrado(s) na origem");
  assert.ok(history.children.every(row => row.children.every(field => field.tag === "span")));
  assert.equal(recorded[1].mensagem_erro, message);
  assert.equal(get("btn-refresh-reconciliation").disabled, false);
});

test("reconciliation toggles in place and collapsed controls are inert", async () => {
  const {get, context} = viewer(data);
  get("tela-diagnostico").hiddenClasses.delete("oculto");
  await context.abrirReconciliacao();
  assert.equal(get("estado-reconciliacao").getAttribute("aria-expanded"), "true");
  assert.equal(get("estado-reconciliacao").hiddenClasses.has("is-active"), true);
  assert.equal(get("reconciliation-shell").querySelector().inert, false);
  await context.abrirReconciliacao();
  assert.equal(get("estado-reconciliacao").getAttribute("aria-expanded"), "false");
  assert.equal(get("reconciliation-shell").querySelector().inert, true);
  assert.equal(get("tela-diagnostico").hiddenClasses.has("oculto"), false);
  context.fecharReconciliacao();
  assert.equal(get("estado-reconciliacao").focused, true);
});

test("a failed refresh exposes the error and clears stale summaries and activity", async () => {
  const {get, context} = viewer({...data, historico: [cycle]});
  await context.carregarReconciliacao();
  assert.equal(get("recon-historico").children.length, 1);
  context.api = async () => { throw new Error("connection unavailable"); };
  await context.carregarReconciliacao();
  assert.match(get("recon-aviso").textContent, /connection unavailable/);
  assert.equal(get("recon-aviso").hiddenClasses.has("oculto"), false);
  assert.equal(get("recon-status").textContent, "—");
  assert.equal(get("recon-history-count").textContent, "—");
  assert.equal(get("recon-contagens").children.length, 0);
  assert.equal(get("recon-historico").children.length, 0);
  assert.equal(get("btn-refresh-reconciliation").disabled, false);
});
