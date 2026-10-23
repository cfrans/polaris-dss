(function() {
  'use strict';
  async function api(path, body, options={}) {
    const response = await fetch('/api/v1/auth/'+path, {method:options.method??(body===undefined?'GET':'POST'), cache:'no-store', headers:{'Content-Type':'application/json','X-Polaris-Auth':'1'}, ...(options.signal?{signal:options.signal}:{}), ...(body===undefined?{}:{body:JSON.stringify(body)})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.mensagem || 'Não foi possível concluir. Tente novamente.');
    return data;
  }
  async function logout() {
    try { await api('sair', {}); } finally { location.href='/login.html'; }
  }
  let resolveSession;
  const ready = new Promise(resolve => { resolveSession=resolve; });
  window.PolarisSession = {api, logout, ready};
  document.addEventListener('DOMContentLoaded', async () => {
    if (location.pathname.endsWith('/login.html')) { resolveSession(null); return; }
    try {
      const status = await api('sessao');
      if (!status.authenticated) { resolveSession(null); location.href='/login.html'; return; }
      window.PolarisSession.user = status.user;
      if(window.PolarisDisplay)await window.PolarisDisplay.load(api);
      document.querySelectorAll('[data-admin]').forEach(el => { el.hidden=status.user.perfil!=='admin'; });
      document.querySelectorAll('[data-session-name]').forEach(el => { el.textContent=status.user.nome; });
      document.querySelectorAll('[data-session-initials]').forEach(el => {
        el.textContent=window.PolarisHeader.initials(status.user.nome,status.user.login);
      });
      document.querySelectorAll('.account-avatar').forEach(el => {
        const role=status.user.perfil==='admin'?'Administrador':'Operador';
        el.title=`${status.user.nome} · ${status.user.login} · ${role}`;
        el.setAttribute('aria-label',`Menu da conta: ${status.user.nome} (${status.user.login}), ${role}`);
      });
      document.querySelectorAll('[data-session-user]').forEach(el => { el.hidden=false; });
      window.PolarisHeader?.bindAccountMenu(document,window.PolarisUI);
      document.querySelectorAll('[data-logout]').forEach(el => el.addEventListener('click',logout));
      resolveSession(status.user);
    } catch { resolveSession(null); location.href='/login.html'; }
  });
})();
