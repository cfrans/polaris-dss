/* Personal presentation only; no incident, approval or evidence mutation. */
(function(root) {
  'use strict';
  const defaults={density:'comfortable',page_size:25,remember_filters:false,time_zone:'local',motion:'system'};
  const auditKeys=['start','end','host','regra','operador','status','decisao','q','ordenar','direcao'];
  function normalize(value={}) {
    return {
      density:value.density==='compact'?'compact':'comfortable',
      page_size:[10,25,50,100].includes(value.page_size)?value.page_size:25,
      remember_filters:value.remember_filters===true,
      time_zone:value.time_zone==='utc'?'utc':'local',
      motion:value.motion==='reduced'?'reduced':'system',
    };
  }
  function zone(mode) {return mode==='utc'?'UTC':Intl.DateTimeFormat().resolvedOptions().timeZone;}
  function formatDate(value,mode='local',options={}) {
    if(value==null||value==='')return '—';
    const date=new Date(value);
    if(!Number.isFinite(+date))return '—';
    return new Intl.DateTimeFormat('pt-BR',{timeZone:zone(mode),day:'2-digit',month:'2-digit',year:'numeric',
      hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',...options}).format(date);
  }
  function formatTime(value,mode='local') {
    const date=new Date(value);
    return Number.isFinite(+date)?new Intl.DateTimeFormat('pt-BR',{timeZone:zone(mode),hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(date):'—';
  }
  function auditSnapshot(value) {
    if(!value||typeof value!=='object'||Array.isArray(value))return {};
    return Object.fromEntries(auditKeys.filter(key=>Object.hasOwn(value,key)&&value[key]!=null).map(key=>[key,value[key]]));
  }
  function create({document,window}) {
    let settings={...defaults},audit={},loaded=false,error=null,request,queue=Promise.resolve();
    const get=()=>({...settings,audit:{...audit}});
    function apply(value) {
      settings=normalize(value);audit=settings.remember_filters?auditSnapshot(value.audit):{};
      document.documentElement.dataset.density=settings.density;
      document.documentElement.dataset.motion=settings.motion;
      document.documentElement.dataset.timeZone=settings.time_zone;
      window.dispatchEvent(new window.CustomEvent('polaris:display-change',{detail:get()}));
    }
    async function call(path,body) {
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
      try {return await request(path,body,{method:body===undefined?'GET':'PUT',signal:controller.signal});}
      finally {clearTimeout(timer);}
    }
    async function load(api) {
      request=api;error=null;
      try {apply(await call('exibicao'));loaded=true;}
      catch(cause) {loaded=false;error=cause.message;apply(defaults);}
      return get();
    }
    async function save(value) {
      if(!loaded)throw new Error('Carregue as preferências antes de salvar.');
      const data=await call('exibicao',normalize(value));apply(data);return get();
    }
    function saveAudit(value) {
      const snapshot=auditSnapshot(value);
      const write=async()=>{
        if(!loaded||!settings.remember_filters)return {saved:false};
        const result=await call('exibicao/auditoria',snapshot);
        if(result.saved&&settings.remember_filters)audit=snapshot;
        return result;
      };
      queue=queue.catch(()=>{}).then(write);return queue;
    }
    return {get,load,save,saveAudit,status:()=>({loaded,error}),defaults:{...defaults},
      zone:()=>zone(settings.time_zone),formatDate:(value,options)=>formatDate(value,settings.time_zone,options),
      formatTime:value=>formatTime(value,settings.time_zone),
      reducedMotion:()=>settings.motion==='reduced'||Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)};
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={defaults,normalize,zone,formatDate,formatTime,auditSnapshot,create};
  if(root.document)root.PolarisDisplay=create({document:root.document,window:root});
})(typeof window!=='undefined'?window:{});
