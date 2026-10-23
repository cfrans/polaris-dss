const test=require('node:test');
const assert=require('node:assert/strict');
const {filterParams,decision,dateValue,pageNumbers,debounce}=require('../../web/auditoria.js');

test('audit filters encode literal text and both local calendar boundaries',()=>{
  const params=filterParams({start:'2026-10-01',end:'2026-10-02',host:'<host>%_ &',regra:'R001',operador:'caio',status:'falha',decisao:'aprovada'});
  assert.equal(params.get('host'),'<host>%_ &');
  assert.equal(params.get('inicio'),new Date('2026-10-01T00:00:00').toISOString());
  assert.equal(params.get('fim'),new Date('2026-10-03T00:00:00').toISOString());
  assert.equal(params.get('status'),'falha');
  assert.equal(params.get('decisao'),'aprovada');
});
test('audit rejects invalid windows instead of exporting an unbounded range',()=>{
  for(const values of [{start:'',end:''},{start:'2026-11-01',end:'2026-10-01'},{start:'2020-01-01',end:'2026-10-01'}]) assert.throws(()=>filterParams(values));
});

test('UTC view uses UTC calendar boundaries independently from the browser timezone',()=>{
  const params=filterParams({start:'2026-10-01',end:'2026-10-02'},'utc');
  assert.equal(params.get('inicio'),'2026-10-01T00:00:00.000Z');
  assert.equal(params.get('fim'),'2026-10-03T00:00:00.000Z');
  assert.equal(dateValue(new Date('2026-10-01T00:30:00Z'),'utc'),'2026-10-01');
});
test('audit distinguishes no decision from rejection and uses local calendar defaults',()=>{
  assert.equal(decision(null),'Sem decisão'); assert.equal(decision(false),'Rejeitada'); assert.equal(decision(true),'Aprovada');
  assert.equal(dateValue(new Date(2026,9,1,23,59)),'2026-10-01');
});

test('numbered pagination exposes first, last and current neighbors without rendering thousands of controls',()=>{
  assert.deepEqual(pageNumbers(2,4),[1,2,3,4]);
  assert.deepEqual(pageNumbers(500,1000),[1,'…',499,500,501,'…',1000]);
  assert.deepEqual(pageNumbers(1,1000),[1,2,'…',1000]);
  assert.deepEqual(pageNumbers(1,1),[1]);
});
test('free search and ordering survive filter serialization for exports',()=>{
  const params=filterParams({start:'2026-10-01',end:'2026-10-02',q:'<script> %_ &',ordenar:'host',direcao:'asc'});
  assert.equal(params.get('q'),'<script> %_ &');assert.equal(params.get('ordenar'),'host');assert.equal(params.get('direcao'),'asc');
});
test('live search debounces typing and explicit actions can cancel pending work',async()=>{
  let calls=0;const queue=debounce(()=>calls++,10);
  queue();queue();queue();await new Promise(resolve=>setTimeout(resolve,30));assert.equal(calls,1);
  queue();queue.cancel();await new Promise(resolve=>setTimeout(resolve,30));assert.equal(calls,1);
});
