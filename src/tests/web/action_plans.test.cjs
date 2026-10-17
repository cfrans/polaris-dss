const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag = "div") {
    this.tag = tag; this.children = []; this.value = ""; this.textContent = ""; this.disabled = false;
    this.attributes = {}; this.classes = new Set();
    this.classList = {toggle: (name, on) => { if (on) this.classes.add(name); else this.classes.delete(name); }};
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  replaceChildren() { this.children = []; this.value = ""; }
  appendChild(child) { this.children.push(child); }
  append(...children) { this.children.push(...children); }
  set innerHTML(value) { throw new Error("Evidence must never be interpreted as HTML"); }
}

const textOf = element => element.children.length
  ? element.children.map(textOf).join(element.tag === "div" ? " | " : "") : element.textContent;
const option = ($, id) => $("plano-opcao").children.find(item => item.value === id);

function setup() {
  const elements = new Map();
  const $ = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const source = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8");
  const start = source.indexOf("function renderActionPlan(");
  const end = source.indexOf("function configurarAviso(", start);
  const decisions = [];
  const context = {$, estado: {}, document: {createElement: tag => new Element(tag)},
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
  assert.equal(textOf($("d-comando")), "fixed-script start");
  context.estado.confirmandoBandaBaixa = true;
  option($, "restart").onclick();
  assert.equal($("plano-opcao").value, "restart");
  assert.equal(option($, "restart").attributes["aria-checked"], "true");
  assert.equal(option($, "start").attributes["aria-checked"], "false");
  assert.equal(textOf($("d-comando")), "fixed-script restart");
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
  assert.ok($("plano-opcao").children.every(item => item.disabled));
  option($, "start").onclick();
  assert.equal($("plano-opcao").value, "restart");
  assert.equal(textOf($("d-comando")), "fixed-script restart");
});

test("service execution is readable and both offered alternatives are visible", () => {
  const {$, context} = setup();
  const start = {...action("start"), operacao: "start", comando: "apply_action.py opaque-base64"};
  const restart = {...action("restart"), operacao: "restart", comando: "apply_action.py another-payload"};
  context.renderActionPlan({id: 9, status: "pendente", plano: {
    versao: "plan", coletado_em: new Date().toISOString(), aviso: "test",
    evidencias: {}, opcoes: [start, restart],
  }});
  assert.equal($("plano-opcao").children.length, 2);
  assert.ok($("plano-opcao").children.every(item => item.tag === "button" && item.attributes.role === "radio"));
  assert.match(textOf(option($, "start")), /start.*90%/);
  assert.match($("plano-opcoes-label").textContent, /2 opção/);
  assert.match(textOf($("d-comando")), /\/usr\/bin\/systemctl start nginx/);
  assert.doesNotMatch(textOf($("d-comando")), /opaque-base64/);
  option($, "restart").onclick();
  assert.match(textOf($("d-comando")), /\/usr\/bin\/systemctl restart nginx/);
});

test("execution detail keeps prose apart from highlighted command blocks", () => {
  const {$, context} = setup();
  const start = {...action("start"), operacao: "start", comando: "apply_action.py payload"};
  context.renderActionPlan({id: 10, status: "pendente", plano: {
    versao: "plan", coletado_em: new Date().toISOString(), aviso: "test", evidencias: {}, opcoes: [start],
  }});
  const blocks = $("d-comando").children;
  const code = blocks.filter(block => block.tag === "pre");
  const prose = blocks.filter(block => block.tag === "p");
  assert.deepEqual(code.map(textOf), [
    "/usr/bin/systemctl show nginx --property=ActiveState --value", "/usr/bin/systemctl start nginx"]);
  assert.ok(prose.every(block => !/systemctl/.test(textOf(block))));
  const tokens = code[1].children[0].children;
  assert.deepEqual(tokens.filter(t => t.className !== "shell-plain").map(t => [t.className, t.textContent]), [
    ["shell-command", "/usr/bin/systemctl"], ["shell-argument", "start"], ["shell-argument", "nginx"]]);
  assert.equal(code[0].children[0].children.find(t => t.className === "shell-flag").textContent,
    "--property=ActiveState");
  const expected = prose.find(block => /Estado esperado/.test(textOf(block)));
  assert.deepEqual(expected.children.map(piece => [piece.tag, piece.textContent]),
    [["span", "Estado esperado: "], ["code", "inactive"], ["span", "."]]);
});

test("missing service exit data never invents a cause or a sudden stop", () => {
  const {$, context} = setup();
  context.renderPlanEvidence($("plano-evidencias"), {estado_servico: "inactive", indicios: []});
  assert.doesNotMatch($("plano-evidencias").children.map(p => p.textContent).join(" "), /Última saída|repentina/);
  context.renderPlanEvidence($("plano-evidencias"), {estado_servico: "inactive", indicios: [],
    saida_servico: {resultado: "success", tipo: "1", codigo: "0"}});
  assert.match($("plano-evidencias").children.map(p => p.textContent).join(" "), /término com código de saída.*não determinam quem/);
});

test("command shows a one-line summary by default and keeps the full procedure as detail", () => {
  const {$, context} = setup();
  const start = {...action("start"), operacao: "start", comando: "apply_action.py payload"};
  const remove = {...action("remove", true), operacao: "remove", comando: "apply_action.py other",
    alvo: {caminho: "/mnt/polaris_test/logs/app-old.log.gz", bytes: 52428800, proprietario: "root", mtime_ns: 0}};
  context.renderActionPlan({id: 11, status: "pendente", plano: {
    versao: "plan", coletado_em: new Date().toISOString(), aviso: "test", evidencias: {}, opcoes: [start, remove],
  }});
  assert.equal(textOf($("d-comando-resumo")), "/usr/bin/systemctl start nginx");
  assert.match(textOf($("d-comando")), /Antes: validar aprovação/);
  assert.equal($("d-comando-detalhes").hidden, false);
  option($, "remove").onclick();
  assert.equal(textOf($("d-comando-resumo")), "Excluir /mnt/polaris_test/logs/app-old.log.gz (50 MiB). Irreversível.");
  assert.match($("plano-alvo").textContent, /50 MiB \(52\.428\.800 bytes\)/);
});

test("sizes are human readable in binary units", () => {
  const {context} = setup();
  assert.equal(context.formatBytes(512), "512 B");
  assert.equal(context.formatBytes(1536), "1,5 KiB");
  assert.equal(context.formatBytes(1419513364), "1,3 GiB");
  assert.equal(context.formatBytes(undefined), "tamanho indisponível");
  context.renderPlanEvidence(context.$("plano-evidencias"), {espaco_livre: 497025024, completo: true,
    arquivos: [{caminho: "/mnt/polaris_test/enchimento.bin", bytes: 1419513364, proprietario: "root", mtime_ns: 0, aberto: false}]});
  const lines = context.$("plano-evidencias").children.map(p => p.textContent);
  assert.match(lines[0], /espaço livre: 474 MiB/);
  assert.match(lines[1], /enchimento\.bin · 1,3 GiB · root/);
});
