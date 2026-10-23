const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {markup,initials,bindAccountMenu}=require('../../web/header.js');
test('home and audit mount the same shell and shared scrolling/clock implementation',()=>{
  for(const page of ['index.html','auditoria.html','preferencias.html','configuracao.html','laboratorio.html']) {
    const source=fs.readFileSync(path.join(__dirname,'../../web',page),'utf8');
    assert.match(source,/data-shared-header/);assert.match(source,/src="header.js"/);assert.match(source,/src="ui.js"/);
    assert.match(source,/src="display.js"/);
    assert.doesNotMatch(source,/<header class="topo">/);
  }
  for(const id of ['server-widget','tools-menu','header-clock','connection-zabbix','estado-reconciliacao']) assert.ok(markup.includes(`id="${id}"`));
});
test('preferences stays in tools while account actions move to the avatar after the clock',()=>{
  const menu=markup.split('<nav class="tools-links"')[1].split('</nav>')[0];
  assert.match(menu,/<a href="preferencias.html"><svg[^]+?icons.svg#settings[^]+?Preferências/);
  assert.doesNotMatch(menu,/contas.html|btn-preferencias/);
  assert.doesNotMatch(menu,/data-logout|Minha conta/);
  const account=markup.split('<nav class="tools-links" aria-label="Sua conta">')[1].split('</nav>')[0];
  assert.match(account,/href="preferencias.html#minha-conta"[^]+?icons.svg#user[^]+?Minha conta/);
  assert.match(account,/class="menu-logout"[^]+?icons.svg#logout[^]+?Sair da conta<\/button>\s*$/);
  assert.ok(markup.indexOf('id="header-clock"')<markup.indexOf('id="account-menu"'));
  assert.equal((markup.match(/data-logout/g)||[]).length,1);
  assert.match(markup,/id="account-toggle"[^]+?aria-controls="account-panel"/);
  assert.match(markup,/data-session-initials aria-hidden="true"/);
});

test('avatar uses first and last initials, preserving accents and a single-name fallback',()=>{
  for(const [name,expected] of [['Caio Franson da Silva','CS'],['  Érica   de Sá  ','ÉS'],['João','J'],['Ana-Clara Costa','AC']]) {
    assert.equal(initials(name),expected);
  }
  assert.equal(initials('', 'operator'),'O');assert.equal(initials(''),'?' );
});

test('account menu supports keyboard, outside click, focus exit and mutually exclusive panels',()=>{
  const elements=new Map(),listeners={};
  const get=id=>{
    if(!elements.has(id)) elements.set(id,{attributes:{'aria-expanded':'false'},listeners:{},
      addEventListener(name,fn){this.listeners[name]=fn;},getAttribute(name){return this.attributes[name];},focus(){this.focused=true;}});
    return elements.get(id);
  };
  const menu=get('account-menu'),trigger=get('account-toggle'),panel=get('account-panel'),link=get('account-link'),logout=get('logout');
  menu.contains=target=>[trigger,panel,link,logout].includes(target);
  panel.querySelectorAll=()=>[link,logout]; panel.querySelector=()=>link;
  const document={getElementById:get,addEventListener:(name,fn)=>{listeners[name]=fn;}};
  const ui={setDisclosure:(panel,button,open)=>{panel.hidden=!open;button.attributes['aria-expanded']=String(open);}};
  bindAccountMenu(document,ui);
  for(const id of ['tools-toggle','server-toggle','estado-reconciliacao']) get(id).attributes['aria-expanded']='true';
  trigger.listeners.click(); assert.equal(trigger.getAttribute('aria-expanded'),'true');
  for(const id of ['tools-toggle','server-toggle','estado-reconciliacao']) assert.equal(get(id).getAttribute('aria-expanded'),'false');
  listeners.click({target:link}); assert.equal(trigger.getAttribute('aria-expanded'),'true');
  listeners.click({target:{}}); assert.equal(trigger.getAttribute('aria-expanded'),'false');
  trigger.listeners.keydown({key:'ArrowDown',preventDefault(){}}); assert.equal(link.focused,true);
  listeners.keydown({key:'Escape',preventDefault(){}}); assert.equal(trigger.focused,true);assert.equal(panel.hidden,true);
  trigger.listeners.click();menu.listeners.focusout({relatedTarget:logout});assert.equal(panel.hidden,false);
  menu.listeners.focusout({relatedTarget:null});assert.equal(panel.hidden,true);
  trigger.listeners.click();logout.listeners.click();assert.equal(panel.hidden,true);
});

test('authenticated session renders literal initials and logout still calls session revocation',async()=>{
  const elements=new Map(),requests=[];
  const el=name=>{if(!elements.has(name))elements.set(name,{hidden:true,attributes:{},listeners:{},
    set textContent(value){this.text=value;},get textContent(){return this.text;},
    set innerHTML(value){assert.fail('identity must render as text');},
    setAttribute(name,value){this.attributes[name]=value;},addEventListener(name,fn){this.listeners[name]=fn;}});return elements.get(name);};
  let ready;
  const user={nome:'Érica de Sá',login:'erica',perfil:'operador'};
  const location={pathname:'/preferencias.html'};
  const window={PolarisHeader:{initials,bindAccountMenu(){}}};
  const document={addEventListener:(name,fn)=>{ready=fn;},querySelectorAll:selector=>[el(selector)]};
  const fetch=async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({authenticated:true,user})};};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../web/session.js'),'utf8'),{window,document,fetch,location});
  await ready();assert.equal(await window.PolarisSession.ready,user);
  assert.equal(el('[data-session-initials]').textContent,'ÉS');
  assert.equal(el('[data-session-user]').hidden,false);
  assert.equal(el('[data-admin]').hidden,true);
  assert.match(el('.account-avatar').attributes['aria-label'],/Érica de Sá.*erica/);
  await el('[data-logout]').listeners.click();
  assert.equal(requests[1].url,'/api/v1/auth/sair');assert.equal(requests[1].options.method,'POST');
  assert.equal(location.href,'/login.html');
});
