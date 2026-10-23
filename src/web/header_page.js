/* Shared read-only header controls outside the incident workbench. */
(function() {
  'use strict';
  const $=id=>document.getElementById(id);
  const tools={ 'btn-diagnostico':'diagnostico','btn-scripts':'scripts' };
  const navigate=tool=>{location.href='./?ferramenta='+tool;};
  async function api(path) {
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),15000);
    try {
      const response=await fetch(path,{cache:'no-store',signal:controller.signal});
      if(response.status===401) {location.href='/login.html?next='+encodeURIComponent(location.pathname);throw new Error('Entre novamente.');}
      if(!response.ok) throw new Error('Consulta indisponível.');
      return await response.json();
    } finally {clearTimeout(timer);}
  }
  const reconciliation=PolarisReconciliation.create({document,ui:PolarisUI,api});
  const closeTools=()=>PolarisUI.setDisclosure($('tools-panel'),$('tools-toggle'),false);
  let busy=false,connectionsCheckedAt=0;
  async function refresh() {
    if(busy||document.hidden) return;
    busy=true;
    try {
      await Promise.allSettled([
        api('/health').then(data=>{$('system-version').textContent=data.versao?'v'+data.versao:'versão —';}).catch(()=>{$('system-version').textContent='versão —';}),
        Date.now()-connectionsCheckedAt<60000?Promise.resolve():api('/api/v1/conectividade').then(data=>{
          for(const check of data.verificacoes) {const indicator=$(check.id==='banco'?'connection-db':check.id==='zabbix'?'connection-zabbix':'');if(indicator)PolarisUI.setConnection(indicator,check.estado,data.verificado_em,check.latencia_ms);}
        }).catch(()=>{for(const id of ['connection-db','connection-zabbix'])PolarisUI.setConnection($(id),'unknown');}).finally(()=>{connectionsCheckedAt=Date.now();}),
        reconciliation.refreshBadge(),
      ]);
    } finally {busy=false;}
  }
  $('tools-toggle').addEventListener('click',()=>PolarisUI.setDisclosure($('tools-panel'),$('tools-toggle'),$('tools-toggle').getAttribute('aria-expanded')!=='true'));
  document.querySelectorAll('.tools-links a,.tools-links button').forEach(el=>el.addEventListener('click',closeTools));
  document.addEventListener('click',event=>{if(!$('tools-menu').contains(event.target))closeTools();});
  document.addEventListener('keydown',event=>{
    if(event.key!=='Escape'||$('audit-detail')?.open) return;
    if($('tools-toggle').getAttribute('aria-expanded')==='true'){closeTools();$('tools-toggle').focus();}
    else if($('estado-reconciliacao').getAttribute('aria-expanded')==='true')reconciliation.close();
  });
  for(const [id,tool] of Object.entries(tools))$(id).addEventListener('click',()=>navigate(tool));
  for(const id of ['connection-db','connection-zabbix'])$(id).addEventListener('click',()=>navigate('diagnostico'));
  $('estado-reconciliacao').addEventListener('click',()=>reconciliation.toggle());
  $('btn-fechar-reconciliacao').addEventListener('click',()=>reconciliation.close());
  $('btn-refresh-reconciliation').addEventListener('click',()=>reconciliation.load());
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)void refresh();});
  void refresh(); setInterval(refresh,15000);
})();
