(function() {
  'use strict';
  const $=id=>document.getElementById(id);
  let user=null, preferencesLoaded=false;

  async function preferences(body) {
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),15000);
    try {
      const response=await fetch('/api/v1/preferencias',{
        method:body===undefined?'GET':'PUT',cache:'no-store',signal:controller.signal,
        headers:{'Content-Type':'application/json'},
        ...(body===undefined?{}:{body:JSON.stringify(body)}),
      });
      if(response.status===401) { location.href='/login.html?next=/preferencias.html'; throw new Error('Entre novamente.'); }
      const data=await response.json();
      if(!response.ok) throw new Error(data.mensagem||'Não foi possível salvar as preferências.');
      return data;
    } finally { clearTimeout(timer); }
  }

  function showSection() {
    const requested=location.hash.slice(1);
    const allowed=['minha-conta','exibicao','operacao',...(user?.perfil==='admin'?['gestao-contas']:[])];
    const selected=allowed.includes(requested)?requested:'minha-conta';
    document.querySelectorAll('[data-settings-panel]').forEach(panel=>{panel.hidden=panel.id!==selected;});
    document.querySelectorAll('.settings-nav a').forEach(link=>{
      if(link.getAttribute('href')==='#'+selected) link.setAttribute('aria-current','page');
      else link.removeAttribute('aria-current');
    });
  }

  async function loadPreferences() {
    preferencesLoaded=false;
    $('preferences-fields').disabled=true;
    $('save-preferences').disabled=true;
    $('retry-preferences').hidden=true;
    try {
      const data=await preferences();
      $('pref-modo').value=data.modo_preferencia;
      $('pref-desconto').value=Math.round(data.desconto_maximo*100);
      $('pref-minimo').value=data.minimo_escolhas;
      $('pref-periodo-ocorrencias').value=data.periodo_ocorrencias_dias;
      $('pref-historico').textContent=data.historico_habilitado
        ? 'Histórico de desempenho habilitado. Alterar as preferências exige atualizar diagnósticos pendentes.'
        : 'Histórico de desempenho desativado neste servidor. As preferências são salvas, mas não afetam as recomendações.';
      preferencesLoaded=true;
      $('preferences-fields').disabled=user.perfil!=='admin';
      $('save-preferences').disabled=user.perfil!=='admin';
    } catch(error) {
      $('pref-historico').textContent='Não foi possível carregar as preferências: '+error.message;
      $('retry-preferences').hidden=false;
    }
  }

  async function listAccounts() {
    try {
      const data=await PolarisSession.api('usuarios');
      $('account-list').replaceChildren();
      $('list-message').textContent='';
      for(const account of data.users) {
        const row=document.createElement('div'); row.className='account-row';
        const text=document.createElement('span');
        const role=account.perfil==='admin'?'Administrador':'Operador';
        text.textContent=`${account.nome} · ${account.login} · ${role} · ${account.ativo?'ativa':'desativada'}`;
        row.appendChild(text);
        if(account.ativo && account.id!==user.id) {
          const button=document.createElement('button');
          button.type='button'; button.className='btn btn-secundario'; button.textContent='Desativar';
          button.addEventListener('click',async()=>{
            if(!confirm('Desativar a conta '+account.login+' e encerrar suas sessões?')) return;
            button.disabled=true;
            try { await PolarisSession.api('usuarios/'+account.id+'/desativar',{}); await listAccounts(); PolarisToast('Conta desativada.'); }
            catch(error) { $('list-message').textContent=error.message; button.disabled=false; }
          });
          row.appendChild(button);
        }
        $('account-list').appendChild(row);
      }
    } catch(error) { $('list-message').textContent=error.message; }
  }

  document.addEventListener('DOMContentLoaded',async()=>{
    user=await PolarisSession.ready;
    if(!user) return;
    $('account-login').textContent=user.login;
    $('account-role').textContent=user.perfil==='admin'?'Administrador':'Operador';
    $('preferences-access').textContent=user.perfil==='admin'
      ? 'As alterações nesta seção valem para toda a instalação.'
      : 'Você pode consultar estes ajustes. Somente administradores podem alterá-los.';
    showSection();
    window.addEventListener('hashchange',showSection);

    const display=window.PolarisDisplay;
    function fillDisplay(value) {
      $('display-density').value=value.density;
      $('display-motion').value=value.motion;
      $('display-zone').value=value.time_zone;
      $('display-page-size').value=String(value.page_size);
      $('display-remember').checked=value.remember_filters;
    }
    function displayState() {
      const status=display.status();
      $('display-fields').disabled=!status.loaded;
      $('display-save').disabled=!status.loaded;
      $('display-reset').disabled=!status.loaded;
      $('display-retry').hidden=status.loaded;
      if(status.loaded)fillDisplay(display.get());
      else $('display-feedback').textContent='Não foi possível carregar sua exibição: '+status.error;
    }
    displayState();
    $('display-retry').addEventListener('click',async()=>{
      $('display-retry').disabled=true;
      try {await display.load(PolarisSession.api);displayState();if(display.status().loaded)$('display-feedback').textContent='Preferências carregadas.';}
      finally {$('display-retry').disabled=false;}
    });
    $('display-reset').addEventListener('click',()=>{
      fillDisplay(display.defaults);
      $('display-feedback').textContent='Padrões preenchidos. Salve para aplicar à sua conta.';
    });
    $('display-form').addEventListener('submit',async event=>{
      event.preventDefault();
      if(!display.status().loaded)return;
      $('display-fields').disabled=true;$('display-save').disabled=true;$('display-reset').disabled=true;
      $('display-feedback').textContent='Salvando…';
      try {
        await display.save({density:$('display-density').value,motion:$('display-motion').value,time_zone:$('display-zone').value,
          page_size:Number($('display-page-size').value),remember_filters:$('display-remember').checked});
        $('display-feedback').textContent='Exibição salva para sua conta.';PolarisToast('Exibição salva.');
      } catch(error) {$('display-feedback').textContent='Não foi possível salvar: '+error.message;}
      finally {$('display-fields').disabled=false;$('display-save').disabled=false;$('display-reset').disabled=false;}
    });

    const passwordForm=$('password-form');
    passwordForm.querySelector('button').disabled=false;
    passwordForm.addEventListener('submit',async event=>{
      event.preventDefault(); const button=passwordForm.querySelector('button'); button.disabled=true;
      $('password-message').textContent='';
      try {
        await PolarisSession.api('senha',{current_password:$('current-password').value,new_password:$('new-password').value});
        passwordForm.reset(); location.href='/login.html';
      } catch(error) { $('password-message').textContent=error.message; }
      finally { button.disabled=false; }
    });

    $('retry-preferences').addEventListener('click',loadPreferences);
    $('preferencias-form').addEventListener('submit',async event=>{
      event.preventDefault();
      if(user.perfil!=='admin'||!preferencesLoaded) return;
      $('save-preferences').disabled=true; $('preferences-fields').disabled=true;
      $('pref-feedback').textContent='';
      try {
        await preferences({
          modo_preferencia:$('pref-modo').value,
          desconto_maximo:Number($('pref-desconto').value)/100,
          minimo_escolhas:Number($('pref-minimo').value),
          periodo_ocorrencias_dias:Number($('pref-periodo-ocorrencias').value),
        });
        $('pref-feedback').textContent='Preferências salvas. Atualize o diagnóstico antes da próxima aprovação.';
        PolarisToast('Preferências salvas.');
      } catch(error) { $('pref-feedback').textContent=error.message; }
      finally { $('save-preferences').disabled=false; $('preferences-fields').disabled=false; }
    });

    if(user.perfil==='admin') {
      const accountForm=$('account-form');
      accountForm.querySelector('button').disabled=false;
      accountForm.addEventListener('submit',async event=>{
        event.preventDefault(); const button=accountForm.querySelector('button'); button.disabled=true;
        $('account-message').textContent='';
        try {
          await PolarisSession.api('usuarios',{username:$('new-username').value,name:$('new-name').value,role:$('new-role').value,password:$('account-password').value});
          accountForm.reset(); await listAccounts(); PolarisToast('Conta criada.');
        } catch(error) { $('account-message').textContent=error.message; }
        finally { button.disabled=false; }
      });
      void listAccounts();
    }
    void loadPreferences();
  });
})();
