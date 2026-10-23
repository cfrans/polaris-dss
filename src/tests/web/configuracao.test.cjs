const test = require("node:test");
const assert = require("node:assert/strict");
const {evaluate, readChecks} = require("../../web/configuracao.js");

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
