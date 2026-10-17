const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor() {
    this.children = []; this.value = ""; this.textContent = ""; this.disabled = false;
    this.classList = {toggle() {}};
  }
  replaceChildren() { this.children = []; this.value = ""; }
  appendChild(child) { this.children.push(child); if (!this.value) this.value = child.value; }
  set innerHTML(value) { throw new Error("Evidence must never be interpreted as HTML"); }
}

function setup() {
  const elements = new Map();
  const $ = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const source = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8");
  const start = source.indexOf("function renderActionPlan(");
  const end = source.indexOf("function configurarAviso(", start);
  const decisions = [];
  const context = {$, estado: {}, document: {createElement: () => new Element()},
    pct: value => `${Math.round(value * 100)}%`, configurarDecisao: inc => decisions.push(inc),
    api: () => { throw new Error("Rendering must not write to the API"); }};
  vm.createContext(context); vm.runInContext(source.slice(start, end), context);
  return {context, $, decisions};
}

function action(id, destructive = false) {
  return {id, titulo: id, confianca: .9, confianca_tecnica: .9, banda: "alta",
    preferencia: {fator: 1, escolhas: 0}, motivo: "evidência", comando: `fixed-script ${id}`,
    rollback: "sem restauração automática", timeout_segundos: 60, destrutiva: destructive,
    alvo: {servico: "nginx", estado: "inactive"}};
}

test("choosing another offered action updates exactly what will be approved and resets confirmation", () => {
  const {$, context, decisions} = setup();
  const plan = {versao: "snapshot", coletado_em: new Date().toISOString(), aviso: "test",
    evidencias: {estado_servico: "inactive", indicios: []}, opcoes: [action("start"), action("restart", true)]};
  context.renderActionPlan({id: 1, status: "pendente", plano: plan});
  assert.equal($("d-comando").textContent, "fixed-script start");
  context.estado.confirmandoBandaBaixa = true;
  $("plano-opcao").value = "restart"; $("plano-opcao").onchange();
  assert.equal($("d-comando").textContent, "fixed-script restart");
  assert.equal(decisions.at(-1).destrutiva, true);
  assert.equal(context.estado.confirmandoBandaBaixa, false);
  assert.equal(context.estado.planoAtual.versao, "snapshot");
});

test("unavailable diagnosis disables approval and untrusted log-shaped text is literal", () => {
  const {$, context} = setup();
  context.renderActionPlan({id: 2, status: "pendente", plano: {
    versao: "failed", coletado_em: new Date().toISOString(), aviso: "failed", opcoes: [],
    evidencias: {erro: '<img src=x onerror="steal()">'},
  }});
  assert.equal($("btn-aprovar").disabled, true);
  assert.equal($("plano-evidencias").children[0].textContent, '<img src=x onerror="steal()">');
});

test("historical chosen action remains selected and cannot be changed", () => {
  const {$, context} = setup();
  context.renderActionPlan({id: 3, status: "sucesso", acao_escolhida: {id: "restart"}, plano: {
    versao: "saved", coletado_em: new Date().toISOString(), aviso: "test", evidencias: {},
    opcoes: [action("start"), action("restart")],
  }});
  assert.equal($("plano-opcao").value, "restart");
  assert.equal($("plano-opcao").disabled, true);
  assert.equal($("d-comando").textContent, "fixed-script restart");
});

test("service execution is readable and both offered alternatives are visible", () => {
  const {$, context} = setup();
  const start = {...action("start"), operacao: "start", comando: "apply_action.py opaque-base64"};
  const restart = {...action("restart"), operacao: "restart", comando: "apply_action.py another-payload"};
  context.renderActionPlan({id: 9, status: "pendente", plano: {
    versao: "plan", coletado_em: new Date().toISOString(), aviso: "test",
    evidencias: {}, opcoes: [start, restart],
  }});
  assert.equal($("plano-opcao").size, 2);
  assert.match($("plano-opcoes-label").textContent, /2 opção/);
  assert.match($("d-comando").textContent, /\/usr\/bin\/systemctl start nginx/);
  assert.doesNotMatch($("d-comando").textContent, /opaque-base64/);
  $("plano-opcao").value = "restart"; $("plano-opcao").onchange();
  assert.match($("d-comando").textContent, /\/usr\/bin\/systemctl restart nginx/);
});

test("missing service exit data never invents a cause or a sudden stop", () => {
  const {$, context} = setup();
  context.renderPlanEvidence($("plano-evidencias"), {estado_servico: "inactive", indicios: []});
  assert.doesNotMatch($("plano-evidencias").children.map(p => p.textContent).join(" "), /Última saída|repentina/);
  context.renderPlanEvidence($("plano-evidencias"), {estado_servico: "inactive", indicios: [],
    saida_servico: {resultado: "success", tipo: "1", codigo: "0"}});
  assert.match($("plano-evidencias").children.map(p => p.textContent).join(" "), /término com código de saída.*não determinam quem/);
});
