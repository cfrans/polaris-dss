const test = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const lab = require('../../web/laboratorio.js');

const config = {scenario: 'service_down', arm: 'baseline', repetition: '1', session: 'ensaio-01',
  operator: 'Operador', version: 'fixture', sha: 'a'.repeat(40), timeout: '300',
  adminUser: 'root', adminKey: '~/.ssh/id_ed25519', runId: '12', incidentId: '19',
  eventId: '50', closeId: '12', reason: 'Ensaio de instrumentação'};

test('all three scenarios use explicit controller commands; baseline does not link incidents', () => {
  for (const scenario of ['service_down', 'cpu_high', 'disk_full']) {
    const commands = lab.draft({...config, scenario});
    assert.ok(commands.run.includes(`--scenario '${scenario}'`));
    assert.equal(commands.link, null);
    assert.equal(Boolean(commands.prepare), scenario === 'disk_full');
  }
  assert.ok(lab.draft({...config, arm: 'hitl'}).link.includes("--incident-id '19'"));
});

test('incomplete metadata, invalid IDs, unsafe paths and excessive CPU deadline produce no command', () => {
  assert.equal(lab.draft({...config, operator: ''}).run, null);
  assert.equal(lab.draft({...config, sha: 'short'}).run, null);
  assert.equal(lab.draft({...config, scenario: 'cpu_high', timeout: '1801'}).run, null);
  assert.equal(lab.draft({...config, closeId: '0'}).reset, null);
  assert.equal(lab.draft({...config, session: '../other'}).assess, null);
  assert.equal(lab.draft({...config, reason: ''}).discard, null);
});

test('shell metacharacters and single quotes stay in one literal argument', () => {
  const reason = "ensaio ' $(printf EXPANDED); `echo nope`";
  const command = lab.draft({...config, reason}).discard;
  const script = 'python3() { printf "%s\\0" "$@"; }\n' + command;
  const result = spawnSync('bash', ['-c', script], {encoding: 'utf8'});
  assert.equal(result.status, 0);
  assert.deepEqual(result.stdout.split('\0').filter(Boolean),
    ['experiment/lab.py', 'discard', '--run-id', '12', '--reason', reason]);
});

test('human assessment requires explicit result and actual steps, preserving literal commands', () => {
  const values = {steps: '0', commands: '<literal>\necho "hi"', resolved: 'false', observations: 'Falha válida'};
  assert.deepEqual(lab.assessment(values), {passos_manuais: 0, comandos_usados: values.commands,
    resolvido: false, observacoes: 'Falha válida'});
  for (const overrides of [{steps: ''}, {resolved: ''}, {observations: ''}, {steps: '-1'}]) {
    assert.throws(() => lab.assessment({...values, ...overrides}));
  }
});
