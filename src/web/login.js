(function() {
  'use strict';
  let bootstrap=false;
  const $=id=>document.getElementById(id);
  const destinations=['/','/configuracao.html','/contas.html','/laboratorio.html'];
  const next=new URLSearchParams(location.search).get('next');
  const destination=destinations.includes(next)?next:'/';
  async function loadAppVersion() {
    try {
      const response=await fetch('/health',{cache:'no-store',credentials:'omit'});
      if (!response.ok) throw new Error('Version unavailable');
      const health=await response.json();
      $('app-version').textContent=health.versao ? `v${health.versao}` : 'Versão indisponível';
    } catch { $('app-version').textContent='Versão indisponível'; }
  }
  function hidePassword() {
    $('password').type='password';
    $('password-toggle').setAttribute('aria-pressed','false');
    $('password-toggle').setAttribute('aria-label','Mostrar senha');
    $('password-toggle').title='Mostrar senha';
    $('password-toggle').querySelector('use').setAttribute('href','icons.svg#eye');
  }
  document.addEventListener('DOMContentLoaded', async () => {
    if (location.protocol !== 'https:' && !['localhost','127.0.0.1','[::1]','::1'].includes(location.hostname)) {
      $('login-error').textContent='Use HTTPS ou o endereço local antes de inserir suas credenciais.';
      return;
    }
    void loadAppVersion();
    try {
      const status=await PolarisSession.api('sessao');
      if (status.authenticated) { location.href=destination; return; }
      document.querySelectorAll('#login-form input, #login-submit').forEach(el=>el.disabled=false);
      $('password-toggle').disabled=false;
      bootstrap=status.bootstrap_required;
      if (bootstrap) {
        document.querySelectorAll('[data-bootstrap]').forEach(el=>el.hidden=false);
        $('bootstrap-code').required=true; $('account-name').required=true;
        $('password').minLength=15; $('password').autocomplete='new-password';
        $('login-submit').textContent='Criar administrador'; $('bootstrap-help').hidden=false;
      }
    } catch(error) { $('login-error').textContent=error.message; $('bootstrap-help').hidden=false; return; }
    $('password-toggle').addEventListener('click',()=>{
      const show=$('password').type==='password';
      $('password').type=show?'text':'password';
      $('password-toggle').setAttribute('aria-pressed',String(show));
      $('password-toggle').setAttribute('aria-label',show?'Ocultar senha':'Mostrar senha');
      $('password-toggle').title=show?'Ocultar senha':'Mostrar senha';
      $('password-toggle').querySelector('use').setAttribute('href',show?'icons.svg#eye-off':'icons.svg#eye');
    });
    $('login-form').addEventListener('submit',async event=>{
      event.preventDefault(); $('login-submit').disabled=true; $('login-error').textContent='';
      hidePassword();
      try {
        const credentials={username:$('username').value, password:$('password').value};
        if (bootstrap) await PolarisSession.api('bootstrap',{...credentials,name:$('account-name').value,code:$('bootstrap-code').value});
        await PolarisSession.api('entrar',credentials);
        $('password').value=''; $('bootstrap-code').value=''; location.href=destination;
      } catch(error) { $('login-error').textContent=error.message; $('password').value=''; }
      finally { $('login-submit').disabled=false; }
    });
  });
})();
