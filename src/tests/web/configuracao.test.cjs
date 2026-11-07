const test = require("node:test");
const assert = require("node:assert/strict");
const {evaluate, readChecks, canVisit, readStoredConfirmations, writeStoredConfirmations, furthestStep,
  targetCommands, agentCommands, webhookUrl, actionPayload, actionCurl} = require("../../web/configuracao.js");

test("navigation blocks bypasses and edits revoke downstream access", () => {
  assert.equal(canVisit(0, ["pendente"]), true);
  assert.equal(canVisit(2, ["manual", "unknown"]), false);
  assert.equal(canVisit(3, ["manual", "ok", "pendente"]), false);
  assert.equal(canVisit(3, ["manual", "ok", "ok"]), true);
  assert.equal(canVisit(6, ["ok", "ok", "ok", "ok", "ok", "ok"]), false);
});

const now = Date.now();
const allManual = {environment: true, zabbix: true, ssh: true, delivery: true, review: true};
const good = () => ({checkedAt: now,
  diagnostic: {verificacoes: ["banco", "migracoes", "base", "alvo"].map(id => ({id, estado: "ok"}))},
  connectivity: {verificacoes: [{id: "zabbix", estado: "ok"}]},
  reconciliation: {status: "sucesso", operacional: true, habilitada: true,
    intervalo_segundos: 30, ultimo_ciclo: {ts_conclusao: new Date(now - 1000).toISOString()}}});

test("unknown or missing checks never complete server stages", () => {
  assert.equal(evaluate({}, allManual, now).count, 2);
  assert.equal(evaluate({checkedAt: now, diagnostic: {verificacoes: []}}, {}, now).count, 0);
});

test("manual acknowledgements remain separate from automatic checks", () => {
  const automatic = evaluate(good(), {}, now);
  assert.equal(automatic.count, 2);
  assert.equal(automatic.stages[2], "pendente");
  assert.equal(automatic.checks.zabbix, "ok");
  assert.equal(evaluate(good(), allManual, now).count, 6);
  assert.equal(evaluate(good(), allManual, now).stages[0], "manual");
});

test("API version/authentication diagnostic alone is not Zabbix access proof", () => {
  const snapshot = good();
  snapshot.connectivity = null;
  snapshot.diagnostic.verificacoes.push({id: "zabbix", estado: "ok"});
  assert.equal(evaluate(snapshot, allManual, now).stages[2], "unknown");
});

test("failed dependency, stale checks and future timestamps revoke completion", () => {
  const snapshot = good();
  snapshot.diagnostic.verificacoes[1].estado = "falha";
  assert.equal(evaluate(snapshot, allManual, now).stages[1], "falha");
  assert.equal(evaluate(good(), allManual, now + 300001).count, 2);
  assert.equal(evaluate(good(), allManual, now - 10000).count, 2);
});

test("saved configuration stays valid across fresh checks while unsaved edits keep stage pending", () => {
  const saved = {zabbix: Math.floor((now - 10 * 60 * 1000) / 1000), ssh: Math.floor((now - 10 * 60 * 1000) / 1000)};
  assert.equal(evaluate(good(), allManual, now, saved).stages[2], "ok");
  assert.equal(evaluate(good(), allManual, now, saved).stages[3], "ok");
  assert.equal(evaluate(good(), allManual, now, {zabbix: 0, ssh: saved.ssh}).stages[2], "pendente");
  assert.equal(evaluate(good(), allManual, now, {zabbix: saved.zabbix, ssh: 0}).stages[3], "pendente");
});

test("reconciliation requires recent successful cycle, not only a success flag", () => {
  for (const patch of [{habilitada: false}, {operacional: false}, {ultimo_ciclo: null},
    {status: "atrasada"}, {intervalo_segundos: 0},
    {ultimo_ciclo: {ts_conclusao: new Date(now - 120000).toISOString()}}]) {
    const snapshot = good();
    Object.assign(snapshot.reconciliation, patch);
    assert.notEqual(evaluate(snapshot, allManual, now).stages[4], "ok");
  }
});

test("checks use GET only, handle partial failures and recover on next request", async () => {
  const requested = [];
  const partial = await readChecks(async (url, options) => {
    requested.push({url, method: options.method});
    if (url.endsWith("reconciliacao")) throw new Error("offline");
    return {ok: true, json: async () => ({verificacoes: []})};
  });
  assert.equal(partial.failed, 1);
  assert.equal(partial.reconciliation, null);
  assert.equal(requested.length, 3);
  assert.ok(requested.every(item => item.method === "GET"));
  const failure = await readChecks(async () => ({ok: false}));
  assert.equal(failure.failed, 3);
  assert.equal(failure.diagnostic, null);
  const recovery = await readChecks(async () => ({ok: true, json: async () => ({})}));
  assert.equal(recovery.failed, 0);
});

test("stored confirmations persist for matching vault revision and resume at furthest unlocked step", () => {
  const map = new Map();
  const storage = {getItem: k => map.get(k) ?? null, setItem: (k, v) => map.set(k, v)};
  writeStoredConfirmations(storage, "rev-1", {environment: true, zabbix: true, ssh: true, delivery: true, review: true, ignored: true});
  assert.deepEqual(readStoredConfirmations(storage, "rev-1"), allManual);
  assert.deepEqual(readStoredConfirmations(storage, "rev-2"), {});
  assert.equal(furthestStep(["manual", "ok", "ok", "ok", "ok", "manual"]), 5);
  assert.equal(furthestStep(["manual", "ok", "pendente", "ok", "ok", "manual"]), 2);
});

test("confirmations are kept per account and follow the newest vault revision", () => {
  const map = new Map();
  const storage = {getItem: k => map.get(k) ?? null, setItem: (k, v) => map.set(k, v)};
  writeStoredConfirmations(storage, "rev-1", {environment: true, review: true}, "ana");
  assert.deepEqual(readStoredConfirmations(storage, "rev-1", "ana"), {environment: true, review: true});
  assert.deepEqual(readStoredConfirmations(storage, "rev-1", "bruno"), {});
  // Saving the polling interval returns a new revision; rewriting under it keeps the answers.
  writeStoredConfirmations(storage, "rev-2", {environment: true, review: true}, "ana");
  assert.deepEqual(readStoredConfirmations(storage, "rev-2", "ana"), {environment: true, review: true});
  assert.deepEqual(readStoredConfirmations(storage, "rev-1", "ana"), {});
});

test("target commands follow the service account and refuse unsafe field values", () => {
  const key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample polaris-dss";
  const commands = targetCommands("svc_polaris", key);
  assert.match(commands, /adduser --disabled-password --gecos '' svc_polaris$/m);
  assert.match(commands, /\/home\/svc_polaris\/\.ssh\/authorized_keys/);
  assert.match(commands, /^echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample polaris-dss' \| sudo tee -a/m);
  assert.match(commands, /svc_polaris ALL=\(root\) NOPASSWD: \/usr\/bin\/timeout/);
  assert.match(commands, /visudo -cf \/etc\/sudoers\.d\/svc_polaris$/);
  const unsafe = targetCommands("x; touch /tmp/owned", "ssh-ed25519 AAAA' ; touch /tmp/x");
  assert.doesNotMatch(unsafe, /touch/);
  assert.match(unsafe, /<usuario>/);
  assert.match(unsafe, /<cole aqui a chave pública gerada acima>/);
});

test("agent commands use the saved Zabbix host and a validated host name", () => {
  const commands = agentCommands("http://172.30.57.17/zabbix/api_jsonrpc.php", "polaris-server");
  assert.match(commands, /Server=172\.30\.57\.17\//);
  assert.match(commands, /Hostname=polaris-server\//);
  assert.match(agentCommands("", "nome com espaço; x"), /Server=<IP-do-Zabbix>.*Hostname=<nome-do-host>/s);
});

test("webhook URL and Trigger action payload match the bundled integration", () => {
  assert.equal(webhookUrl({protocol: "http:", hostname: "172.30.58.23", port: "8000"}), "http://172.30.58.23:8000/webhook/zabbix");
  assert.match(webhookUrl({protocol: "http:", hostname: "localhost", port: "8000"}), /IP-do-servidor-Polaris:8000/);
  const {params} = actionPayload();
  assert.equal(params.filter.evaltype, 3);
  assert.equal(params.filter.formula, "(A and B) or (C and D)");
  assert.deepEqual(params.filter.conditions.map(c => [c.formulaid, c.conditiontype, c.operator]),
    [["A", 25, 0], ["B", 26, 0], ["C", 13, 0], ["D", 3, 2]]);
  assert.equal(params.filter.conditions[1].value2, "polaris");
  assert.equal(params.filter.conditions[1].value, "enabled");
  assert.equal(params.operations[0].opmessage.default_msg, 1);
  assert.match(actionCurl("http://10.0.0.2/zabbix/api_jsonrpc.php"), /--data @polaris-action\.json http:\/\/10\.0\.0\.2\/zabbix\/api_jsonrpc\.php$/);
  assert.match(actionCurl(""), /<URL-da-API-do-Zabbix>/);
});
