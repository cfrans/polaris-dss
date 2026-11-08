const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture() {
  let now = Date.now(), fail = false, cycleReads = 0;
  const elements = new Map(), intervals = new Map(), listeners = {};
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      hidden: false, value: '', textContent: '', dataset: {}, disabled: false,
      lastChild: {textContent: ''}, firstChild: {textContent: 'Etapa'}, classList: {toggle() {}},
      addEventListener(event, fn) { this[event] = fn; },
      setAttribute() {}, removeAttribute() {}, focus() {},
      querySelector(selector) { return get(id + selector); }, querySelectorAll() { return []; },
    });
    return elements.get(id);
  };
  const buttons = Array.from({length: 6}, (_, i) => get('step-' + i));
  const panels = Array.from({length: 6}, (_, i) => get('panel-' + i));
  const confirmations = {environment: true, zabbix: true, ssh: true, delivery: true, review: true};
  const fetcher = async route => {
    let data;
    if (route.endsWith('/acesso')) data = {authenticated: true, secure_transport: true};
    else if (route.includes('configuracao?')) data = {revision: 'r1', zabbix: {url: 'http://10.0.0.2', mode: 'token'}, ssh: {user: 'polaris', host: '10.0.0.4'}, validated: {zabbix: 1, ssh: 1}, polling_interval: 30};
    else if (route.endsWith('/reconciliacao')) {
      cycleReads++;
      if (fail) throw new Error('offline');
      data = {status: 'sucesso', operacional: true, habilitada: true, intervalo_segundos: 30,
        ultimo_ciclo: {ts_conclusao: new Date(now - 1000).toISOString()}};
    } else if (route.endsWith('/ciencia')) data = {acknowledged: true};
    else data = {verificacoes: ['banco', 'migracoes', 'base', 'alvo', 'zabbix'].map(id => ({id, estado: 'ok'}))};
    return {ok: true, json: async () => data};
  };
  class Clock extends Date { static now() { return now; } }
  const document = {hidden: false, getElementById: get,
    querySelector: get, querySelectorAll: selector => selector === '[data-step]' ? buttons : selector === '[data-panel]' ? panels : [],
    addEventListener: (event, fn) => { listeners[event] = fn; }};
  const window = {fetch: fetcher, PolarisUI: {formatTime: () => ''}, PolarisCopy: {bind() {}},
    PolarisSession: {ready: Promise.resolve({login: 'caio'})},
    localStorage: {getItem: () => JSON.stringify({revision: 'r1', confirmations}), setItem() {}}};
  const source = fs.readFileSync(path.join(__dirname, '../../web/configuracao.js'), 'utf8');
  vm.runInNewContext(source, {window, document, fetch: fetcher, Date: Clock, URL, AbortController,
    location: {hostname: '10.0.0.3', protocol: 'http:', port: '8000'},
    setInterval: (fn, ms) => intervals.set(ms, fn), setTimeout, clearTimeout});
  return {get, document, listeners, intervals, buttons, reads: () => cycleReads,
    advance(ms) { now += ms; }, fail(value) { fail = value; },
    ready: () => new Promise(setImmediate)};
}

test('step 6 keeps reading successful reconciliation across multiple cycle validity windows', async () => {
  const f = fixture(); await f.ready();
  assert.equal(f.get('setup-count').textContent, '6 de 6');
  assert.equal(f.get('setup-next').disabled, false);
  const initialReads = f.reads();
  for (let n = 0; n < 24; n++) {
    f.advance(10000);
    await f.intervals.get(10000)();
    assert.equal(f.buttons[4].dataset.state, 'ok');
    assert.equal(f.get('setup-next').disabled, false);
  }
  assert.equal(f.reads(), initialReads + 24);
  assert.match(f.get('agent-command').textContent, /Hostname=polaris-server\//);
  assert.equal(f.get('agent-host-name').textContent, 'polaris-server');
});

test('failed reconciliation read blocks completion and recovers without saving the interval', async () => {
  const f = fixture(); await f.ready();
  f.fail(true); await f.intervals.get(10000)();
  assert.equal(f.get('setup-next').disabled, true);
  f.fail(false); await f.intervals.get(10000)();
  assert.equal(f.get('setup-next').disabled, false);
  f.document.hidden = true; const reads = f.reads();
  await f.intervals.get(10000)(); assert.equal(f.reads(), reads);
  f.advance(120000); f.document.hidden = false;
  f.listeners.visibilitychange(); await f.ready();
  assert.equal(f.buttons[4].dataset.state, 'ok');
  assert.equal(f.get('setup-next').disabled, false);
});
