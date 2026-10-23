(function() {
  'use strict';
  async function api(path, body) {
    const response = await fetch('/api/v1/auth/'+path, {method: body===undefined?'GET':'POST', cache:'no-store', headers:{'Content-Type':'application/json','X-Polaris-Auth':'1'}, ...(body===undefined?{}:{body:JSON.stringify(body)})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.mensagem || 'Não foi possível concluir. Tente novamente.');
    return data;
  }
  async function logout() {
    try { await api('sair', {}); } finally { location.href='/login.html'; }
  }
  window.PolarisSession = {api, logout};
  document.addEventListener('DOMContentLoaded', async () => {
    if (location.pathname.endsWith('/login.html')) return;
    try {
      const status = await api('sessao');
      if (!status.authenticated) { location.href='/login.html'; return; }
      window.PolarisSession.user = status.user;
      document.querySelectorAll('[data-admin]').forEach(el => { el.hidden=status.user.perfil!=='admin'; });
      document.querySelectorAll('[data-session-name]').forEach(el => { el.textContent=status.user.nome; });
      document.querySelectorAll('[data-logout]').forEach(el => el.addEventListener('click',logout));
    } catch { location.href='/login.html'; }
  });
})();
