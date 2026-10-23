(function() {
  'use strict';
  const $=id=>document.getElementById(id);
  async function list() {
    try {
      const data=await PolarisSession.api('usuarios');
      $('account-list').replaceChildren();
      for (const user of data.users) {
        const row=document.createElement('div'); row.className='account-row';
        const text=document.createElement('span'); text.textContent=`${user.nome} · ${user.login} · ${user.perfil} · ${user.ativo?'ativa':'desativada'}`; row.appendChild(text);
        if (user.ativo && user.id!==PolarisSession.user?.id) {
          const button=document.createElement('button'); button.className='btn btn-secundario'; button.textContent='Desativar';
          button.addEventListener('click',async()=>{
            if (!confirm('Desativar a conta '+user.login+' e encerrar suas sessões?')) return;
            button.disabled=true;
            try { await PolarisSession.api('usuarios/'+user.id+'/desativar',{}); await list(); PolarisToast('Conta desativada.'); }
            catch(error) { $('list-message').textContent=error.message; button.disabled=false; }
          }); row.appendChild(button);
        }
        $('account-list').appendChild(row);
      }
    } catch(error) { $('list-message').textContent=error.message; }
  }
  document.addEventListener('DOMContentLoaded',async()=>{
    const status=await PolarisSession.api('sessao').catch(()=>null);
    if (!status?.authenticated) return;
    PolarisSession.user=status.user;
    if (status.user.perfil==='admin') await list();
    $('password-form').addEventListener('submit',async event=>{
      event.preventDefault(); const button=event.submitter; button.disabled=true;
      try {
        await PolarisSession.api('senha',{current_password:$('current-password').value,new_password:$('new-password').value});
        $('current-password').value=''; $('new-password').value=''; location.href='/login.html';
      } catch(error) { $('password-message').textContent=error.message; }
      finally { button.disabled=false; }
    });
    $('account-form').addEventListener('submit',async event=>{
      event.preventDefault(); const button=event.submitter; button.disabled=true;
      try {
        await PolarisSession.api('usuarios',{username:$('new-username').value,name:$('new-name').value,role:$('new-role').value,password:$('account-password').value});
        $('account-form').reset(); await list(); PolarisToast('Conta criada.');
      } catch(error) { $('account-message').textContent=error.message; }
      finally { button.disabled=false; }
    });
  });
})();
