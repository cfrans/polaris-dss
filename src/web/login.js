(function() {
  'use strict';
  let bootstrap=false;
  const $=id=>document.getElementById(id);
  const destinations=['/','/configuracao.html','/contas.html','/laboratorio.html'];
  const next=new URLSearchParams(location.search).get('next');
  const destination=destinations.includes(next)?next:'/';
  document.addEventListener('DOMContentLoaded', async () => {
    if (location.protocol !== 'https:' && !['localhost','127.0.0.1','[::1]','::1'].includes(location.hostname)) {
      $('login-error').textContent='Use HTTPS ou o endereço local antes de inserir suas credenciais.';
      return;
    }
    try {
      const status=await PolarisSession.api('sessao');
      if (status.authenticated) { location.href=destination; return; }
      document.querySelectorAll('#login-form input, #login-submit').forEach(el=>el.disabled=false);
      bootstrap=status.bootstrap_required;
      if (bootstrap) {
        $('login-title').textContent='Crie seu primeiro acesso';
        $('login-lead').textContent='Uma conta administradora para preparar e acompanhar sua instalação.';
        document.querySelectorAll('[data-bootstrap]').forEach(el=>el.hidden=false);
        $('bootstrap-code').required=true; $('account-name').required=true;
        $('password').minLength=15; $('password').autocomplete='new-password';
        $('login-submit').textContent='Criar administrador'; $('bootstrap-help').hidden=false;
      }
    } catch(error) { $('login-error').textContent=error.message; $('bootstrap-help').hidden=false; return; }
    $('login-form').addEventListener('submit',async event=>{
      event.preventDefault(); $('login-submit').disabled=true; $('login-error').textContent='';
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
