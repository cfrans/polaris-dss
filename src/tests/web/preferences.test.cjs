const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../web/preferencias.js'),'utf8');

function fixture(role, fail=false) {
  const elements=new Map(), calls=[], listeners={}, nav=[];
  const get=id=>{
    if(!elements.has(id)) elements.set(id,{
      id,hidden:false,disabled:true,value:'',textContent:'',listeners:{},attributes:{},
      addEventListener(name,fn){this.listeners[name]=fn;},
      setAttribute(name,value){this.attributes[name]=value;},
      removeAttribute(name){delete this.attributes[name];},
      getAttribute(name){return this.attributes[name];},
      querySelector(){return get(id+'-button');},replaceChildren(){},appendChild(){},reset(){},
    });
    return elements.get(id);
  };
  for(const section of ['minha-conta','exibicao','operacao','gestao-contas']) {
    const link=get('link-'+section); link.attributes.href='#'+section; nav.push(link);
  }
  const user={id:7,nome:'<img src=x onerror=alert(1)>',login:'reader',perfil:role};
  const location={hash:'#gestao-contas'}, expected={modo_preferencia:'desempate',desconto_maximo:.1,minimo_escolhas:5,periodo_ocorrencias_dias:30,historico_habilitado:true};
  const context={location,AbortController,setTimeout,clearTimeout,PolarisToast(){},
    PolarisSession:{ready:Promise.resolve(user),api:async(route,body)=>{calls.push({route,body});return {users:[]};}},
    window:{addEventListener:(name,fn)=>{listeners[name]=fn;},PolarisDisplay:{status:()=>({loaded:true}),get:()=>({density:'comfortable',motion:'system',time_zone:'local',page_size:25,remember_filters:false})}},
    document:{getElementById:get,addEventListener:(name,fn)=>{listeners[name]=fn;},
      querySelectorAll:selector=>selector==='[data-settings-panel]'?['minha-conta','exibicao','operacao','gestao-contas'].map(get):nav,
      createElement:()=>get('generated')},
    fetch:async(route,options)=>{calls.push({route,options});if(fail)throw new Error('offline');return {ok:true,status:200,json:async()=>expected};},
  };
  vm.runInNewContext(source,context);
  return {get,calls,listeners,location,ready:async()=>{await listeners.DOMContentLoaded();await new Promise(setImmediate);},recover(){fail=false;}};
}

test('operator can view operation settings, never loads other accounts, and cannot submit changes',async()=>{
  const f=fixture('operador'); await f.ready();
  assert.equal(f.get('minha-conta').hidden,false);
  assert.equal(f.get('gestao-contas').hidden,true);
  assert.equal(f.get('account-login').textContent,'reader');
  assert.equal(f.get('preferences-fields').disabled,true);
  assert.match(f.get('preferences-access').textContent,/Somente administradores/);
  f.location.hash='#operacao'; f.listeners.hashchange();
  assert.equal(f.get('minha-conta').hidden,true);
  assert.equal(f.get('operacao').hidden,false);
  assert.equal(f.get('pref-periodo-ocorrencias').value,30);
  await f.get('preferencias-form').listeners.submit({preventDefault(){}});
  assert.equal(f.calls.length,1);
  assert.equal(f.calls[0].options.method,'GET');
});

test('admin cannot overwrite settings after a failed read and can retry then save',async()=>{
  const f=fixture('admin',true);await f.ready();
  assert.equal(f.get('gestao-contas').hidden,false);
  assert.equal(f.get('preferences-fields').disabled,true);
  assert.equal(f.get('save-preferences').disabled,true);
  assert.equal(f.get('retry-preferences').hidden,false);
  await f.get('preferencias-form').listeners.submit({preventDefault(){}});
  assert.equal(f.calls.filter(call=>call.options?.method==='PUT').length,0);
  f.recover(); await f.get('retry-preferences').listeners.click();
  assert.equal(f.get('save-preferences').disabled,false);
  assert.equal(f.get('retry-preferences').hidden,true);
  f.get('pref-desconto').value='20'; f.get('pref-periodo-ocorrencias').value='60';
  await f.get('preferencias-form').listeners.submit({preventDefault(){}});
  const body=JSON.parse(f.calls.find(call=>call.options?.method==='PUT').options.body);
  assert.equal(body.desconto_maximo,.2);assert.equal(body.periodo_ocorrencias_dias,60);
  assert.match(f.get('pref-feedback').textContent,/salvas/);
  assert.equal(f.get('preferences-fields').disabled,false);
});
