(function(root) {
  'use strict';
  const LOOPBACK=['localhost','127.0.0.1','[::1]','::1'];
  const DESTINATIONS=['/','/configuracao.html','/contas.html','/preferencias.html','/laboratorio.html','/auditoria.html'];

  function isLocal(location) { return location.protocol==='https:' || LOOPBACK.includes(location.hostname); }
  function publishedPort(location) { return location.port || (location.protocol==='https:'?'443':'80'); }
  function tunnelCommand(location) { return `ssh -N -L 8000:localhost:${publishedPort(location)} usuario@${location.hostname}`; }
  function pairingCommand(location) { return `docker compose exec polaris-api python -m src.engine.pairing --address ${location.hostname}`; }
  function destinationFor(search) {
    const next=new URLSearchParams(search).get('next');
    return DESTINATIONS.includes(next)?next:'/';
  }

  if (typeof module!=='undefined' && module.exports) {
    module.exports={isLocal,tunnelCommand,pairingCommand,destinationFor};
    return;
  }

  const document=root.document;
  const location=root.location;
  const $=id=>document.getElementById(id);
  const destination=destinationFor(location.search);
  let bootstrap=false;

  async function loadAppVersion() {
    try {
      const response=await root.fetch('/health',{cache:'no-store',credentials:'omit'});
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

  function showBlocked() {
    $('login-form').hidden=true;
    $('network-blocked').hidden=false;
    $('tunnel-command').textContent=tunnelCommand(location);
  }

  function showPairing(access) {
    $('login-form').hidden=true;
    $('pairing-form').hidden=false;
    $('pairing-command').textContent=pairingCommand(location);
    if (access.code_minutes && access.pairing_days) {
      $('pairing-validity').textContent=`O código vale uma vez, por ${access.code_minutes} minutos. Este navegador fica pareado por ${access.pairing_days} dias.`;
    }
    $('pairing-code').disabled=false;
    $('pairing-submit').disabled=false;
    $('pairing-form').addEventListener('submit',async event=>{
      event.preventDefault();
      $('pairing-submit').disabled=true; $('login-error').textContent='';
      try {
        await root.PolarisSession.api('pareamento',{code:$('pairing-code').value});
        $('pairing-code').value='';
        location.reload();
      } catch(error) { $('login-error').textContent=error.message; }
      finally { $('pairing-submit').disabled=false; }
    });
  }

  function enableLogin(status) {
    document.querySelectorAll('#login-form input, #login-submit').forEach(el=>el.disabled=false);
    $('password-toggle').disabled=false;
    bootstrap=status.bootstrap_required;
    if (!bootstrap) return;
    document.querySelectorAll('[data-bootstrap]').forEach(el=>el.hidden=false);
    $('auth-card').classList.add('is-wide');
    $('bootstrap-code').required=true; $('account-name').required=true;
    $('password').minLength=15; $('password').autocomplete='new-password';
    $('login-submit').textContent='Criar administrador'; $('bootstrap-help').hidden=false;
  }

  document.addEventListener('DOMContentLoaded', async () => {
    void loadAppVersion();
    root.PolarisCopy?.bind(document);
    let access;
    try { access=await root.PolarisSession.api('pareamento'); }
    catch(error) { $('login-error').textContent=error.message; return; }
    if (!isLocal(location)) {
      if (access.state==='blocked') { showBlocked(); return; }
      if (access.state!=='paired') { showPairing(access); return; }
      $('paired-note').hidden=false;
    }
    try {
      const status=await root.PolarisSession.api('sessao');
      if (status.authenticated) { location.href=destination; return; }
      enableLogin(status);
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
        if (bootstrap) await root.PolarisSession.api('bootstrap',{...credentials,name:$('account-name').value,code:$('bootstrap-code').value});
        await root.PolarisSession.api('entrar',credentials);
        $('password').value=''; $('bootstrap-code').value='';
        // The first administrator continues straight into the installation assistant.
        location.href=bootstrap?'/configuracao.html':destination;
      } catch(error) { $('login-error').textContent=error.message; $('password').value=''; }
      finally { $('login-submit').disabled=false; }
    });
  });
})(typeof globalThis!=='undefined'?globalThis:this);
