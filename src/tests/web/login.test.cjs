const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../web/login.js'),'utf8');
const {isLocal,tunnelCommand,pairingCommand,destinationFor}=require('../../web/login.js');

async function render(location, responses) {
  let ready;
  const calls=[];
  const elements=new Map();
  const get=id=>{ if(!elements.has(id)) elements.set(id,{id,disabled:true,hidden:true,textContent:'',value:'',classList:{add(){}},addEventListener(){}}); return elements.get(id); };
  const context={location,URLSearchParams,fetch:async()=>({ok:false}),
    PolarisSession:{api:async(route,body)=>{calls.push({route,body}); return responses[route]??{};}},
    document:{getElementById:get,addEventListener:(name,callback)=>ready=callback,
      querySelectorAll:selector=>selector==='#login-form input, #login-submit'?['username','password','login-submit'].map(get):[]}};
  vm.runInNewContext(source,context);
  await ready();
  return {elements,calls,get};
}

test('remote HTTP without pairing shows the tunnel and never enables credentials',async()=>{
  const location={protocol:'http:',hostname:'192.0.2.20',port:'8000',search:''};
  const result=await render(location,{pareamento:{enabled:false,state:'blocked'}});
  assert.deepEqual(result.calls.map(call=>call.route),['pareamento']);
  assert.equal(result.elements.get('network-blocked').hidden,false);
  assert.equal(result.elements.get('login-form').hidden,true);
  assert.equal(result.elements.get('tunnel-command').textContent,'ssh -N -L 8000:localhost:8000 usuario@192.0.2.20');
  assert.equal(result.get('username').disabled,true);
});

test('remote HTTP with pairing enabled asks for the code before any login request',async()=>{
  const location={protocol:'http:',hostname:'192.0.2.20',port:'8000',search:''};
  const result=await render(location,{pareamento:{enabled:true,state:'required',code_minutes:10,pairing_days:7}});
  assert.deepEqual(result.calls.map(call=>call.route),['pareamento']);
  assert.equal(result.elements.get('pairing-form').hidden,false);
  assert.equal(result.elements.get('pairing-code').disabled,false);
  assert.match(result.elements.get('pairing-command').textContent,/src\.engine\.pairing --address 192\.0\.2\.20$/);
  assert.match(result.elements.get('pairing-validity').textContent,/10 minutos.*7 dias/);
  assert.equal(result.get('password').disabled,true);
});

test('a paired browser signs in with a visible clear-text warning',async()=>{
  const location={protocol:'http:',hostname:'192.0.2.20',port:'8000',search:''};
  const result=await render(location,{pareamento:{enabled:true,state:'paired'},sessao:{authenticated:false,bootstrap_required:false}});
  assert.deepEqual(result.calls.map(call=>call.route),['pareamento','sessao']);
  assert.equal(result.elements.get('paired-note').hidden,false);
  assert.equal(result.get('username').disabled,false);
});

test('external return URL cannot redirect a logged-in session outside Polaris',async()=>{
  const location={protocol:'https:',hostname:'polaris.example',search:'?next=https://attacker.example'};
  await render(location,{pareamento:{state:'secure'},sessao:{authenticated:true}});
  assert.equal(location.href,'/');
});

test('helpers build tunnel and pairing commands from the address in use',()=>{
  assert.equal(isLocal({protocol:'http:',hostname:'localhost'}),true);
  assert.equal(isLocal({protocol:'http:',hostname:'10.0.0.5'}),false);
  assert.equal(tunnelCommand({protocol:'http:',hostname:'10.0.0.5',port:''}),'ssh -N -L 8000:localhost:80 usuario@10.0.0.5');
  assert.equal(pairingCommand({hostname:'10.0.0.5'}),'docker compose exec polaris-api python -m src.engine.pairing --address 10.0.0.5');
  assert.equal(destinationFor('?next=/auditoria.html'),'/auditoria.html');
  assert.equal(destinationFor('?next=//evil.example'),'/');
});
