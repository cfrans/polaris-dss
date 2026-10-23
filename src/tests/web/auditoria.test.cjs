const test=require('node:test');
const assert=require('node:assert/strict');
const {filterParams,decision,dateValue}=require('../../web/auditoria.js');

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
test('audit distinguishes no decision from rejection and uses local calendar defaults',()=>{
  assert.equal(decision(null),'Sem decisão'); assert.equal(decision(false),'Rejeitada'); assert.equal(decision(true),'Aprovada');
  assert.equal(dateValue(new Date(2026,9,1,23,59)),'2026-10-01');
});
