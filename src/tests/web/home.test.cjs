const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ui = require("../../web/ui.js");

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.value = "";
    this.text = "";
    this.classes = new Set();
    this.listeners = {};
    this.dataset = {};
    this.attributes = new Map();
    this.classList = {
      add: name => this.classes.add(name),
      remove: name => this.classes.delete(name),
      toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
      contains: name => this.classes.has(name),
    };
  }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(""); }
  set innerHTML(_) { assert.fail("incident fields must be rendered as literal text"); }
  replaceChildren(...children) { this.text = ""; this.children = children; }
  appendChild(child) { this.children.push(child); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  querySelector() { return this.child ??= new Element(); }
  focus() { this.focused = true; }
}

function home(api, storage = new Map()) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const requests = [];
  const opened = [];
  const document = {title: "", createElement: tag => new Element(tag),
    createTextNode: text => Object.assign(new Element("#text"), {text}),
    querySelector: selector => { assert.equal(selector, ".painel"); return get("panel"); },
    querySelectorAll: selector => { assert.equal(selector, ".item.ativo"); return [get("selected-row")]; }};
  const context = vm.createContext({$: get, document,
    window: {PolarisUI: {...ui, icon: () => new Element("svg")}},
    requestAnimationFrame: callback => { callback(); return 1; },
    cancelAnimationFrame: () => {},
    matchMedia: () => ({matches: false}),
    localStorage: storage.getItem ? storage : {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
    estado: {selecionado: null, confirmandoBandaBaixa: false},
    formatarData: value => value,
    api: async (...args) => { requests.push(args); return api(...args); },
    abrir: id => opened.push(id),
  });
  const source = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8");
  vm.runInContext(source.split("/* ---------- home ---------- */")[1]
    .split("/* ---------- ciência sobre a execução remota ---------- */")[0], context);
  return {get, context, requests, opened, document};
}

const incident = {id: 42, regra: "R003", hostname: "host-01", nome_regra: "Serviço nginx",
  status: "executando", ts_criacao: "2026-10-13T20:00:00Z"};

test("background overview only reads incidents; opening one requires an explicit click", async () => {
  const hostileText = '<img src=x onerror="alert(1)">';
  const {get, context, requests, opened} = home(async () => ({itens: [{...incident, hostname: hostileText}]}));
  await context.loadRecentIncidents();
  assert.deepEqual(requests, [["/api/v1/incidentes?status=&limit=6&include_unmatched=false"]]);
  assert.deepEqual(opened, []);
  const button = get("recent-incidents").children[0].children[0];
  assert.equal(button.tag, "button");
  assert.match(button.children[1].textContent, /<img src=x onerror="alert\(1\)">/);
  assert.equal(button.children[2].textContent, "Em execução");
  await context.loadRecentIncidents();
  assert.equal(get("recent-incidents").children[0].children[0], button, "unchanged polling preserves keyboard focus");
  button.listeners.click();
  assert.deepEqual(opened, [42]);
});

test("failed overview refresh removes stale results and a later success recovers", async () => {
  let fail = false;
  const {get, context} = home(async () => {
    if (fail) throw new Error("offline");
    return {itens: [incident]};
  });
  await context.loadRecentIncidents();
  fail = true;
  await context.loadRecentIncidents();
  assert.equal(get("recent-incidents").children.length, 0);
  assert.match(get("recent-message").textContent, /Não foi possível consultar/);
  assert.equal(get("recent-message").classes.has("oculto"), false);
  fail = false;
  await context.loadRecentIncidents();
  assert.equal(get("recent-incidents").children.length, 1);
  assert.equal(get("recent-message").classes.has("oculto"), true);
});

test("a slow response from the previous filter cannot overwrite the current filter", async () => {
  let release;
  const {get, context, requests} = home(route => route.includes("status=&")
    ? new Promise(resolve => { release = resolve; }) : Promise.resolve({itens: []}));
  const previous = context.loadRecentIncidents();
  get("recent-filter").value = "falha";
  await context.loadRecentIncidents();
  release({itens: [incident]});
  await previous;
  assert.equal(requests[1][0], "/api/v1/incidentes?status=falha&limit=6&include_unmatched=false");
  assert.equal(get("recent-incidents").children.length, 0);
  assert.equal(get("recent-message").textContent, "Nenhum incidente com regra neste filtro. Você pode incluir os alertas sem regra abaixo.");
});

test("home navigation clears selection without viewing or approving an incident", () => {
  const {get, context, requests} = home(() => assert.fail("home navigation must not write or view incidents"));
  context.updateHomeQueue(0, new Date("2026-10-13T15:00:00Z"));
  const checkedAt = get("home-queue-time").textContent;
  context.estado.selecionado = 42;
  context.estado.confirmandoBandaBaixa = true;
  get("tools-toggle").setAttribute("aria-expanded", "true");
  get("panel").classes.add("oculto");
  let prevented = false;
  context.showHome({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(context.estado.selecionado, null);
  assert.equal(context.estado.confirmandoBandaBaixa, false);
  assert.equal(get("detalhe").attributes.get("aria-hidden"), "true");
  assert.equal(get("detalhe").classes.has("is-hidden"), true);
  assert.equal(get("panel").classes.has("oculto"), false);
  assert.equal(get("panel").classes.has("queue-empty"), true);
  assert.equal(get("tools-toggle").getAttribute("aria-expanded"), "false");
  assert.equal(get("home-queue-time").textContent, checkedAt, "navigation does not pretend to query again");
  assert.deepEqual(requests, []);
});

test("hiding recent records persists locally and never removes a pending decision or writes to the API", async () => {
  const storage = new Map();
  const item = {...incident, status: "pendente"};
  const {get, context, requests, opened} = home(async () => ({itens: [item]}), storage);
  context.updateHomeQueue(1);
  await context.loadRecentIncidents();
  get("recent-incidents").children[0].children[1].listeners.click();
  assert.equal(get("recent-incidents").children.length, 0);
  assert.equal(get("hidden-count").textContent, "1");
  assert.equal(get("home-pending").textContent, "1");
  assert.equal(get("panel").classes.has("queue-empty"), false);
  assert.deepEqual(opened, []);
  assert.ok(requests.every(args => args.length === 1 && args[0].startsWith("/api/v1/incidentes?")));
  assert.equal(JSON.parse(storage.get("polaris.hidden.incidents.v1"))[0].status, undefined,
    "hidden metadata must not pretend a stored status is still current");
  const reloaded = home(async () => ({itens: [item]}), storage);
  await reloaded.context.loadRecentIncidents();
  assert.equal(reloaded.get("recent-incidents").children.length, 0);
  reloaded.get("hidden-incidents").children[0].children[1].listeners.click();
  assert.equal(reloaded.get("recent-incidents").children.length, 1);
  assert.equal(reloaded.get("hidden-count").textContent, "0");
});

test("invalid or unavailable browser storage does not break the list or claim persistence", async () => {
  const storage = {getItem: () => "invalid JSON", setItem: () => { throw new Error("blocked"); }};
  const {get, context} = home(async () => ({itens: [incident]}), storage);
  await context.loadRecentIncidents();
  context.setRecordHidden(incident, true);
  assert.equal(get("recent-incidents").children.length, 0);
  assert.match(get("hidden-feedback").textContent, /apenas nesta sessão/);
});

test("returning home prevents a delayed result from being rendered into another view", async () => {
  let release;
  const {get, context} = home(() => new Promise(resolve => { release = resolve; }));
  const source = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8");
  context.INTERVALO_RESULTADO_MS = 0;
  context.setTimeout = setTimeout;
  context.escapar = text => text;
  const body = {innerHTML: ""};
  const originalGet = context.$;
  context.$ = id => id === "resultado-corpo" ? body : originalGet(id);
  vm.runInContext(source.split("/* ---------- decisão ---------- */")[1]
    .split("/* ---------- simulação ---------- */")[0], context);
  context.estado.selecionado = 42;
  const pendingResult = context.mostrarResultado(42);
  const initialMarkup = body.innerHTML;
  context.showHome();
  release({status: "sucesso", output: "old output"});
  await pendingResult;
  assert.equal(body.innerHTML, initialMarkup);
  assert.equal(get("detalhe").attributes.get("aria-hidden"), "true");
});

test("an unavailable queue is never shown as empty; capped results are not an exact total", () => {
  const {get, context, document} = home(() => ({itens: []}));
  context.updateHomeQueue(0);
  assert.equal(get("home-title").textContent, "Nenhuma decisão pendente");
  assert.equal(get("panel").classes.has("queue-empty"), true);
  context.updateHomeQueue(null);
  assert.match(get("home-title").textContent, /Não foi possível consultar/);
  assert.equal(get("home-pending").textContent, "—");
  assert.equal(get("panel").classes.has("queue-empty"), false);
  context.updateHomeQueue(50);
  assert.equal(get("home-pending").textContent, "50+");
  assert.match(document.title, /50\+/);
});


test("unmatched alerts are hidden by default and the explicit preference survives a reload", async () => {
  const storage = new Map();
  const rows = [{...incident, id: 1, regra: null, nome_regra: null, status: "no_match"},
    {...incident, id: 2, regra: null, nome_regra: null, status: "encerrado_na_origem"},
    {...incident, id: 3, regra: "R999", nome_regra: null}];
  const {get, context, requests} = home(async () => ({itens: rows}), storage);
  await context.loadRecentIncidents();
  assert.equal(get("show-unmatched").checked, false);
  assert.equal(get("recent-incidents").children.length, 1);
  assert.match(get("recent-incidents").textContent, /Regra R999/);
  assert.match(requests[0][0], /include_unmatched=false/);
  await context.setUnmatchedVisibility(true);
  assert.equal(get("recent-incidents").children.length, 3);
  assert.match(requests[1][0], /include_unmatched=true/);
  const reloaded = home(async () => ({itens: rows}), storage);
  await reloaded.context.loadRecentIncidents();
  assert.equal(reloaded.get("show-unmatched").checked, true);
  assert.equal(reloaded.get("recent-incidents").children.length, 3);
  get("recent-filter").value = "no_match";
  await context.setUnmatchedVisibility(false);
  assert.equal(get("recent-filter").value, "");
  assert.ok(requests.every(args => args.length === 1), "preference never writes to the server");
});

test("approving shows a spinner while the action runs and restores the button on failure", async () => {
  let fail;
  const {get, context} = home(() => new Promise((_, reject) => { fail = reject; }));
  const source = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8");
  context.alert = () => {};
  context.OPERADOR = "operador";
  vm.runInContext(source.split("/* ---------- decisão ---------- */")[1]
    .split("/* ---------- simulação ---------- */")[0], context);
  get("btn-aprovar").textContent = "Aprovar e executar";
  const pending = context.decidir(7, true);
  const button = get("btn-aprovar");
  assert.equal(button.classes.has("carregando"), true);
  assert.equal(button.attributes.get("aria-busy"), "true");
  assert.equal(button.children[0].className, "indicador-giro");
  assert.match(button.textContent, /Executando/);
  assert.equal(button.disabled, true);
  fail(new Error("recusado"));
  await pending;
  assert.equal(button.classes.has("carregando"), false);
  assert.equal(button.attributes.has("aria-busy"), false);
  assert.equal(button.textContent, "Aprovar e executar");
  assert.equal(button.disabled, false);
});

test("a finished execution fills the end time without reloading the card", async () => {
  const {get, context} = home(() => ({status: "sucesso", output: "compress: /mnt/x.log -> /mnt/x.log.gz",
    exit_code: 0, ts_conclusao: "2026-10-17T21:30:24Z", mttr_segundos: 34.2}));
  const source = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8");
  context.INTERVALO_RESULTADO_MS = 0;
  context.escapar = text => text;
  context.formatIncidentDate = value => `data:${value}`;
  context.Intl = Intl;
  const body = {innerHTML: ""};
  const originalGet = context.$;
  context.$ = id => id === "resultado-corpo" ? body : originalGet(id);
  vm.runInContext(source.split("/* ---------- decisão ---------- */")[1]
    .split("/* ---------- simulação ---------- */")[0], context);
  get("d-fim").textContent = "Sem registro de fim";
  context.estado.selecionado = 304;
  await context.mostrarResultado(304);
  assert.equal(get("d-fim").textContent, "data:2026-10-17T21:30:24Z");
  assert.match(get("d-fim").attributes ? get("d-fim").title : "", /Resolvida/);
  assert.match(body.innerHTML, /sucesso/);
});

