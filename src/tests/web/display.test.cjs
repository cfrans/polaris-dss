const test=require('node:test');
const assert=require('node:assert/strict');
const {defaults,normalize,formatDate,formatTime,auditSnapshot,create}=require('../../web/display.js');

function instance(request) {
  const document={documentElement:{dataset:{}}},events=[];
  const window={CustomEvent:class{constructor(type,value){this.type=type;this.detail=value.detail;}},dispatchEvent:event=>events.push(event),matchMedia:()=>({matches:false})};
  const display=create({document,window});
  return {display,document,window,events,load:()=>display.load(request)};
}

test('display normalizes only presentation options, with explicit safe defaults',()=>{
  assert.deepEqual(normalize({density:'html',page_size:100000,remember_filters:'true',motion:'anything',time_zone:'Etc/Injected'}),defaults);
  assert.deepEqual(auditSnapshot({host:'literal <host>',token:'secret',usuario_id:99,offset:900}),{host:'literal <host>'});
  assert.equal(formatTime('2026-10-01T00:00:00Z','utc'),'00:00:00');
  assert.match(formatDate('2026-10-01T00:00:00Z','utc'),/01\/10\/2026.*00:00:00/);
  assert.equal(formatDate('invalid'),'—');assert.equal(formatDate(null),'—');
});

test('settings persist through authenticated requests and update density/motion without storing credentials',async()=>{
  let saved={...defaults,audit:{}},writes=0;
  const env=instance(async(path,body)=>{if(body){saved={...body,audit:{}};writes++;}return saved;});
  await env.load();
  assert.equal(env.display.status().loaded,true);
  await env.display.save({...defaults,density:'compact',motion:'reduced',time_zone:'utc'});
  assert.equal(env.document.documentElement.dataset.density,'compact');
  assert.equal(env.display.reducedMotion(),true);assert.equal(env.display.zone(),'UTC');
  assert.equal(env.events.at(-1).type,'polaris:display-change');assert.equal(writes,1);
  const second=instance(async()=>saved);await second.load();assert.equal(second.display.get().density,'compact');
  env.window.matchMedia=()=>({matches:true});
  await env.display.save({...defaults,motion:'system'});assert.equal(env.display.reducedMotion(),true);
});

test('failed preference read leaves defaults active and blocks overwriting until a successful retry',async()=>{
  const env=instance(async()=>{throw new Error('offline');});await env.load();
  assert.equal(env.display.status().loaded,false);assert.equal(env.document.documentElement.dataset.density,'comfortable');
  await assert.rejects(env.display.save(defaults),/Carregue/);
  await env.display.load(async()=>({...defaults,density:'compact'}));assert.equal(env.display.status().loaded,true);
});

test('remembered filters are serialized in order and opting out stops queued persistence',async()=>{
  const writes=[];let release;
  const env=instance(async(path,body)=>{
    if(!body)return {...defaults,remember_filters:true};
    if(path==='exibicao')return {...body,audit:{}};
    writes.push(body.q);
    if(body.q==='first')await new Promise(resolve=>{release=resolve;});
    return {saved:true};
  });
  await env.load();
  const first=env.display.saveAudit({q:'first'});await new Promise(setImmediate);
  const second=env.display.saveAudit({q:'second'});
  await env.display.save(defaults);release();await first;await second;
  assert.deepEqual(writes,['first']);assert.deepEqual(env.display.get().audit,{});
});
