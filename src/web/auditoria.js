(function(root) {
  'use strict';
  const states={pendente:'Pendente',executando:'Em execução',sucesso:'Sucesso',falha:'Falha',timeout:'Tempo esgotado',rejeitado:'Rejeitado',no_match:'Sem regra',encerrado_na_origem:'Encerrado no Zabbix'};
  const decision=value=>value===true?'Aprovada':value===false?'Rejeitada':'Sem decisão';
  const stamp=value=>value?root.PolarisUI.formatDate(value):'Não registrado';
  function dateValue(date,mode='local') {
    if(mode==='utc')return date.toISOString().slice(0,10);
    return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  }
  function filterParams(values,mode='local') {
    const suffix=mode==='utc'?'T00:00:00Z':'T00:00:00';
    const start=new Date(values.start+suffix), end=new Date(values.end+suffix);
    if(mode==='utc')end.setUTCDate(end.getUTCDate()+1);else end.setDate(end.getDate()+1);
    if (!Number.isFinite(+start)||!Number.isFinite(+end)||start>=end||end-start>366*86400000) throw new Error('Escolha um período válido de até 366 dias.');
    const query=new URLSearchParams({inicio:start.toISOString(),fim:end.toISOString()});
    for (const key of ['host','regra','operador','status','decisao','q','ordenar','direcao']) if(values[key]) query.set(key,values[key].trim());
    return query;
  }
  function pageNumbers(current,total) {
    const pages=new Set([1,total]);
    for(let page=Math.max(1,current-1);page<=Math.min(total,current+1);page++)pages.add(page);
    if(total<=7)for(let page=1;page<=total;page++)pages.add(page);
    const result=[];let previous=0;
    for(const page of [...pages].sort((a,b)=>a-b)) {if(page<1)continue;if(page-previous>1)result.push('…');result.push(page);previous=page;}
    return result;
  }
  function debounce(callback,delay=250) {
    let timer;const queued=()=>{clearTimeout(timer);timer=setTimeout(callback,delay);};
    queued.cancel=()=>clearTimeout(timer);return queued;
  }
  if(typeof module!=='undefined'&&module.exports) module.exports={filterParams,decision,dateValue,pageNumbers,debounce};
  if(!root.document) return;
  const $=id=>document.getElementById(id);
  let pageSize=25,sort='criacao',direction='desc';
  let applied, appliedView, offset=0, total=0, listController, detailController, sequence=0, detailSequence=0;
  const node=(tag,text,className)=>{const el=document.createElement(tag); if(text!=null)el.textContent=String(text); if(className)el.className=className; return el;};
  function badge(text,tone) { const el=node('span',text,'audit-badge'); el.dataset.tone=tone||'neutral'; return el; }
  function exportEnabled(value) { $('audit-csv').disabled=!value; $('audit-json').disabled=!value; }
  function syncQuery() {applied.set('q',$('audit-search').value.trim());applied.set('ordenar',sort);applied.set('direcao',direction);Object.assign(appliedView,{q:applied.get('q'),ordenar:sort,direcao:direction});}
  function updateSort() {
    document.querySelectorAll('[data-sort]').forEach(button=>{
      const active=button.dataset.sort===sort;
      button.closest('th').setAttribute('aria-sort',active?(direction==='asc'?'ascending':'descending'):'none');
      button.querySelector('use').setAttribute('href','icons.svg#'+(active?'sort-'+direction:'sort'));
      button.title='Ordenar '+button.textContent.trim()+' em ordem '+(active&&direction==='asc'?'decrescente':'crescente');
    });
  }
  function renderPages() {
    const current=Math.floor(offset/pageSize)+1, pages=Math.min(Math.max(1,Math.ceil(total/pageSize)),Math.floor(100000/pageSize)+1);
    $('audit-page-label').textContent=`Página ${current} de ${pages}`;
    const container=$('audit-page-numbers');container.replaceChildren();
    if(pages<=1)return;
    for(const value of pageNumbers(current,pages)) {
      if(value==='…') {container.append(node('span','…'));continue;}
      const button=node('button',value,'btn btn-secundario');button.type='button';button.setAttribute('aria-label','Página '+value);
      if(value===current)button.setAttribute('aria-current','page');
      button.addEventListener('click',()=>{offset=(value-1)*pageSize;void loadList();});container.append(button);
    }
  }
  async function request(path,signal) {
    const response=await fetch('/api/v1/auditoria'+path,{cache:'no-store',signal});
    if(response.status===401) { location.href='/login.html?next=/auditoria.html'; throw new Error('Sua sessão terminou. Entre novamente.'); }
    if(!response.ok) { const data=await response.json().catch(()=>({})); throw new Error(data.mensagem||(typeof data.detail==='string'?data.detail:'Não foi possível consultar a auditoria. Confira os filtros e tente novamente.')); }
    return response;
  }
  async function loadList() {
    listController?.abort(); listController=new AbortController();
    const controller=listController, current=++sequence, timeout=setTimeout(()=>controller.abort(),15000);
    $('audit-rows').replaceChildren(); $('audit-empty').hidden=true; $('audit-summary').textContent='Consultando registros…'; $('audit-message').textContent=''; $('audit-message').dataset.kind='error';
    $('audit-prev').disabled=true; $('audit-next').disabled=true; $('audit-page-label').textContent='—'; $('audit-page-numbers').replaceChildren(); exportEnabled(false);
    try {
      const params=new URLSearchParams(applied); params.set('limit',pageSize); params.set('offset',offset);
      const data=await (await request('?'+params,controller.signal)).json();
      if(current!==sequence) return;
      if(!Array.isArray(data.itens)||!Number.isInteger(data.total)||data.total<0) throw new Error('Resposta de auditoria inválida. Atualize a consulta.');
      total=data.total;
      for(const row of data.itens) {
        const tr=node('tr');
        const identity=node('td'); identity.append(node('strong','#'+row.id)); tr.append(identity);
        tr.append(node('td',stamp(row.ts_criacao),'audit-created'));
        const host=node('td'); host.append(node('strong',row.hostname||'Não registrado')); tr.append(host);tr.append(node('td',row.regra_disparada||'Sem regra'));
        const human=node('td'); human.append(badge(decision(row.decisao_humana),row.decisao_humana===true?'good':row.decisao_humana===false?'warn':'')); tr.append(human);
        const status=node('td'); status.append(badge(states[row.status_execucao]||row.status_execucao,{sucesso:'good',falha:'bad',timeout:'bad',executando:'info'}[row.status_execucao])); tr.append(status);
        tr.append(node('td',row.operador||'Não registrado'));
        const action=node('td'), button=node('button','Ver registro','btn btn-secundario'); button.type='button'; button.setAttribute('aria-label',`Ver registro ${row.id}`); button.addEventListener('click',()=>openDetail(row.id)); action.append(button); tr.append(action); $('audit-rows').append(tr);
      }
      $('audit-empty').hidden=data.itens.length>0;
      if(!data.itens.length&&total>0) { $('audit-empty').querySelector('h3').textContent='Esta página não tem mais registros'; $('audit-empty').querySelector('p').textContent='Volte à página anterior ou aplique os filtros novamente.'; }
      else { $('audit-empty').querySelector('h3').textContent='Nenhum registro neste recorte'; $('audit-empty').querySelector('p').textContent='Experimente ampliar o período ou remover um filtro.'; }
      $('audit-summary').textContent=total===0?'Nenhum registro encontrado':data.itens.length===0?`Nenhum registro nesta página; ${total} no período`:`${offset+1}–${offset+data.itens.length} de ${total} registros`;
      renderPages();
      $('audit-prev').disabled=offset===0; $('audit-next').disabled=offset+pageSize>=total||offset+pageSize>100000; exportEnabled(total>0);
      if(root.PolarisDisplay.get().remember_filters) {
        void root.PolarisDisplay.saveAudit({...appliedView}).then(result=>{
          if(current===sequence)$('audit-memory-message').textContent=result.saved?'Filtros, busca e ordenação lembrados para sua conta.':'';
        }).catch(()=>{if(current===sequence)$('audit-memory-message').textContent='A consulta está disponível, mas não foi possível lembrar os filtros. Tente aplicar novamente.';});
      }
    } catch(error) { if(current===sequence) { $('audit-summary').textContent='Consulta indisponível'; $('audit-message').textContent=error.name==='AbortError'?'A consulta demorou demais. Tente novamente.':error.message; } }
    finally { clearTimeout(timeout); }
  }
  function detailContent(row) {
    const body=$('audit-detail-body'); body.replaceChildren();
    const facts=node('dl',null,'audit-facts');
    const fact=(label,value)=>{const group=node('div');group.append(node('dt',label),node('dd',value??'Não registrado'));facts.append(group);};
    fact('Host',row.hostname); fact('IP',row.ip_address); fact('Evento Zabbix',row.id_evento); fact('Regra registrada',row.regra_disparada);
    fact('Decisão humana',decision(row.decisao_humana)); fact('Resultado / estado',states[row.status_execucao]||row.status_execucao); fact('Operador registrado',row.operador); fact('Código de saída',row.exit_code);
    fact('Versão do motor',row.versao_motor); fact('Versão da base',row.versao_kb); body.append(facts);
    if(row.motivo_rejeicao) { body.append(node('h3','Motivo da rejeição'),node('pre',row.motivo_rejeicao)); }
    body.append(node('h3','Linha do tempo'));
    const timeline=node('ol',null,'audit-timeline');
    for(const [key,label] of [['ts_deteccao','Detectado'],['ts_criacao','Registrado no Polaris'],['ts_exibicao','Apresentado no atendimento'],['ts_aprovacao',row.decisao_humana===false?'Rejeitado':'Decisão registrada'],['ts_conclusao','Concluído']]) {
      const item=node('li'), time=node('time',stamp(row[key])); if(row[key])time.dateTime=row[key]; item.append(node('span',label),time); timeline.append(item);
    } body.append(timeline);
    if(row.ts_criacao&&row.ts_conclusao) {const seconds=(new Date(row.ts_conclusao)-new Date(row.ts_criacao))/1000;if(seconds>=0)body.append(node('p',`Registro → conclusão: ${seconds.toLocaleString('pt-BR',{maximumFractionDigits:3})} s. Duração operacional do atendimento.`));}
    body.append(node('h3','Comando registrado'),node('pre',row.comando_executado??'Não registrado'),node('p','O comando pode ter sido apenas proposto. A decisão humana e o resultado acima indicam autorização e desfecho.'));
    body.append(node('h3','Saída registrada'),node('pre',row.output_execucao??'Não registrada'),node('h3','Erro registrado'),node('pre',row.output_erro??'Não registrado'));
    for(const [title,value] of [['Ação escolhida',row.explicabilidade?.acao_escolhida],['Explicabilidade e evidências',row.explicabilidade],['Versão dos scripts',row.versao_scripts],['Comando de verificação',row.comando_verificacao]]) {
      const section=node('details'); section.append(node('summary',title),node('pre',value==null?'Não registrado':typeof value==='string'?value:JSON.stringify(value,null,2))); body.append(section);
    }
  }
  async function openDetail(id) {
    detailController?.abort(); detailController=new AbortController(); const controller=detailController,current=++detailSequence,timeout=setTimeout(()=>controller.abort(),15000);
    $('audit-detail-title').textContent='Atendimento #'+id; $('audit-detail-body').replaceChildren(node('p','Consultando registro…')); if(!$('audit-detail').open)$('audit-detail').showModal();
    try { const row=await (await request('/'+id,controller.signal)).json(); if(current===detailSequence&&$('audit-detail').open)detailContent(row); }
    catch(error) {if(current===detailSequence&&$('audit-detail').open)$('audit-detail-body').replaceChildren(node('p',error.name==='AbortError'?'A consulta demorou demais. Feche e abra o registro novamente.':error.message));}
    finally {clearTimeout(timeout);}
  }
  async function download(format) {
    exportEnabled(false); $('audit-message').textContent=''; $('audit-message').dataset.kind='error'; const params=new URLSearchParams(applied); params.set('formato',format);
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000),current=sequence;
    try {
      const response=await request('/exportar?'+params,controller.signal), blob=await response.blob();
      if(current!==sequence) return;
      const url=URL.createObjectURL(blob), link=node('a'); link.href=url; link.download='polaris-auditoria.'+format; document.body.append(link); link.click(); link.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
      $('audit-message').dataset.kind='success'; $('audit-message').textContent='Arquivo exportado com os filtros aplicados.';
    } catch(error) {if(current===sequence)$('audit-message').textContent=error.name==='AbortError'?'A exportação demorou demais. Refine os filtros e tente novamente.':error.message;}
    finally {clearTimeout(timeout); if(current===sequence)exportEnabled(total>0);}
  }
  function defaults() {const now=new Date(),start=new Date(now),mode=root.PolarisDisplay.get().time_zone;if(mode==='utc')start.setUTCDate(start.getUTCDate()-29);else start.setDate(start.getDate()-29);$('audit-start').value=dateValue(start,mode);$('audit-end').value=dateValue(now,mode);}
  const liveSearch=debounce(()=>{offset=0;syncQuery();void loadList();});
  function apply() {
    liveSearch.cancel();
    try {appliedView={start:$('audit-start').value,end:$('audit-end').value,host:$('audit-host').value,regra:$('audit-rule').value,operador:$('audit-operator').value,status:$('audit-status').value,decisao:$('audit-decision').value};applied=filterParams(appliedView,root.PolarisDisplay.get().time_zone);syncQuery();updateSort();offset=0;void loadList();}
    catch(error){applied=null;++sequence;listController?.abort();total=0;$('audit-rows').replaceChildren();$('audit-empty').hidden=true;$('audit-summary').textContent='Confira os filtros';$('audit-page-label').textContent='—';$('audit-page-numbers').replaceChildren();$('audit-prev').disabled=true;$('audit-next').disabled=true;exportEnabled(false);$('audit-message').dataset.kind='error';$('audit-message').textContent=error.message;}
  }
  document.addEventListener('DOMContentLoaded',async()=>{
    if(!await root.PolarisSession.ready)return;
    const display=root.PolarisDisplay.get();
    pageSize=display.page_size;$('audit-page-size').value=String(pageSize);
    $('audit-zone-note').textContent='Período de criação, até 366 dias. Datas e horários em '+root.PolarisDisplay.zone()+'.';
    defaults();
    if(display.remember_filters) {
      const saved=display.audit;
      for(const [key,id] of [['start','audit-start'],['end','audit-end'],['host','audit-host'],['regra','audit-rule'],['operador','audit-operator'],['status','audit-status'],['decisao','audit-decision'],['q','audit-search']])if(saved[key]!=null)$(id).value=saved[key];
      if(saved.ordenar)sort=saved.ordenar;if(saved.direcao)direction=saved.direcao;
    }
    $('audit-filters').addEventListener('submit',event=>{event.preventDefault();apply();});
    $('audit-reset').addEventListener('click',()=>{$('audit-filters').reset();$('audit-search').value='';sort='criacao';direction='desc';defaults();apply();});
    $('audit-search').addEventListener('input',event=>{
      if(event.isComposing)return;
      if(!applied){apply();return;}
      ++sequence;listController?.abort();exportEnabled(false);$('audit-prev').disabled=true;$('audit-next').disabled=true;$('audit-page-numbers').replaceChildren();$('audit-rows').replaceChildren();$('audit-empty').hidden=true;$('audit-message').textContent='';$('audit-summary').textContent='Buscando…';liveSearch();
    });
    $('audit-search').addEventListener('compositionend',()=>{$('audit-search').dispatchEvent(new Event('input'));});
    $('audit-page-size').addEventListener('change',()=>{liveSearch.cancel();pageSize=Number($('audit-page-size').value);offset=0;if(!applied){apply();return;}syncQuery();void loadList();});
    document.querySelectorAll('[data-sort]').forEach(button=>button.addEventListener('click',()=>{liveSearch.cancel();direction=sort===button.dataset.sort&&direction==='asc'?'desc':'asc';sort=button.dataset.sort;offset=0;if(!applied){apply();return;}syncQuery();updateSort();void loadList();}));
    $('audit-prev').addEventListener('click',()=>{offset=Math.max(0,offset-pageSize);void loadList();}); $('audit-next').addEventListener('click',()=>{offset+=pageSize;void loadList();});
    $('audit-csv').addEventListener('click',()=>download('csv')); $('audit-json').addEventListener('click',()=>download('json'));
    $('audit-close').addEventListener('click',()=>$('audit-detail').close()); $('audit-detail').addEventListener('close',()=>{++detailSequence;detailController?.abort();});
    apply();
  });
})(typeof window!=='undefined'?window:{});
