const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../web/login.js'),'utf8');

async function render(location, status) {
  let ready, requests=0;
  const elements=new Map();
  const get=id=>{ if(!elements.has(id)) elements.set(id,{disabled:true,textContent:'',addEventListener(){}}); return elements.get(id); };
  const context={location,URLSearchParams,PolarisSession:{api:async()=>{requests++; return status;}},
    document:{getElementById:get,addEventListener:(name,callback)=>ready=callback,querySelectorAll:()=>[]}};
  vm.runInNewContext(source,context);
  await ready();
  return {elements,requests};
}

test('remote HTTP never enables credentials or submits authentication',async()=>{
  const result=await render({protocol:'http:',hostname:'192.0.2.20',search:''},{});
  assert.equal(result.requests,0);
  assert.match(result.elements.get('login-error').textContent,/HTTPS/);
});

test('external return URL cannot redirect a logged-in session outside Polaris',async()=>{
  const location={protocol:'https:',hostname:'polaris.example',search:'?next=https://attacker.example'};
  await render(location,{authenticated:true});
  assert.equal(location.href,'/');
});
