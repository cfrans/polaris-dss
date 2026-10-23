/* Shared, static application shell. Incident data is rendered separately as text. */
(function(root) {
  'use strict';
  const markup = `<div class="topbar-shell">
<header class="topo">
  <a id="brand-home" class="marca" href="./" aria-label="Polaris DSS — página inicial">
    <img class="brand-mark" src="polaris-mark.svg" width="38" height="38" alt="">
    <span class="brand-name">Polaris <span class="brand-suffix">DSS</span></span>
    <span id="system-version" class="system-version">v—</span>
  </a>
  <div class="estado">
    <div class="connection-group" aria-label="Conectividade do Polaris">
      <button id="connection-zabbix" class="connection-indicator" data-service="Zabbix" data-state="unknown"
              type="button" aria-label="Zabbix: aguardando verificação"><span class="status-dot" aria-hidden="true"></span>Zabbix</button>
      <button id="connection-db" class="connection-indicator" data-service="Banco" data-state="unknown"
              type="button" aria-label="Banco: aguardando verificação"><span class="status-dot" aria-hidden="true"></span>Banco</button>
    </div>
    <div id="server-widget" class="server-widget">
      <button id="server-toggle" class="server-toggle" type="button" aria-expanded="false" aria-controls="server-panel" title="Recursos do servidor Polaris">
        <svg class="icon" aria-hidden="true"><use href="icons.svg#server"></use></svg>
        <span class="server-caption">Servidor</span><span id="server-summary">Sem dados</span>
      </button>
      <div id="server-panel" class="server-popover disclosure-shell" aria-hidden="true">
        <div class="disclosure-clip" inert>
          <section class="server-resources" aria-labelledby="server-title">
            <div class="server-heading"><h2 id="server-title">Servidor Polaris</h2>
              <button id="server-refresh" class="icon-button" type="button" aria-label="Atualizar recursos" title="Atualizar recursos"><svg class="icon" aria-hidden="true"><use href="icons.svg#refresh"></use></svg></button>
            </div>
            <p id="server-source" class="server-source">Métricas pelo Zabbix</p>
            <div class="resource-row"><span>CPU em uso</span><strong id="server-cpu-value">—</strong></div>
            <div id="server-cpu-bar" class="resource-track" role="img" aria-label="CPU em uso: sem dados"><span></span></div>
            <small id="server-cpu-time" class="resource-time">Sem coleta disponível</small>
            <div class="resource-row"><span>Memória em uso</span><strong id="server-memory-value">—</strong></div>
            <div id="server-memory-bar" class="resource-track" role="img" aria-label="Memória em uso: sem dados"><span></span></div>
            <small id="server-memory-time" class="resource-time">Sem coleta disponível</small>
            <p id="server-message" class="server-message" role="status">Consultando métricas…</p>
          </section>
        </div>
      </div>
    </div>
    <button id="estado-reconciliacao" class="pilula pilula-botao recon-toggle" type="button"
            aria-expanded="false" aria-controls="reconciliation-shell">
      <span class="status-dot" aria-hidden="true"></span><span id="reconciliation-label">Reconciliação</span>
      <svg class="icon chevron" aria-hidden="true"><use href="icons.svg#chevron"></use></svg>
    </button>
    <div id="tools-menu" class="tools-menu">
      <button id="tools-toggle" class="icon-button settings-toggle" type="button" title="Ferramentas"
              aria-label="Ferramentas" aria-expanded="false" aria-controls="tools-panel">
        <svg class="icon" aria-hidden="true"><use href="icons.svg#settings"></use></svg>
      </button>
      <div id="tools-panel" class="tools-popover disclosure-shell" aria-hidden="true">
        <div class="disclosure-clip" inert>
          <nav class="tools-links" aria-label="Ferramentas do Polaris">
            <a href="./"><svg class="icon" aria-hidden="true"><use href="icons.svg#home"></use></svg>Painel de incidentes</a>
            <a href="auditoria.html"><svg class="icon" aria-hidden="true"><use href="icons.svg#eye"></use></svg>Auditoria</a>
            <a href="configuracao.html" data-admin hidden><svg class="icon" aria-hidden="true"><use href="icons.svg#settings"></use></svg>Configuração inicial</a>
            <button id="btn-diagnostico" type="button"><svg class="icon" aria-hidden="true"><use href="icons.svg#diagnostic"></use></svg>Diagnóstico</button>
            <a href="preferencias.html"><svg class="icon" aria-hidden="true"><use href="icons.svg#settings"></use></svg>Preferências</a>
            <button id="btn-scripts" type="button"><svg class="icon" aria-hidden="true"><use href="icons.svg#code"></use></svg>Scripts e ciência</button>
            <a href="laboratorio.html"><svg class="icon" aria-hidden="true"><use href="icons.svg#lab"></use></svg>Laboratório de ensaios</a>
            <button id="btn-simular" class="oculto" type="button"><svg class="icon" aria-hidden="true"><use href="icons.svg#play"></use></svg>Simular incidente</button>
          </nav>
        </div>
      </div>
    </div>
    <time id="header-clock" class="header-clock" aria-live="off">
      <span id="clock-time">—:—:—</span><small id="clock-date"></small>
    </time>
    <div id="account-menu" class="account-menu" data-session-user hidden>
      <button id="account-toggle" class="account-avatar" type="button" aria-label="Menu da conta"
              aria-expanded="false" aria-controls="account-panel">
        <span data-session-initials aria-hidden="true">—</span>
      </button>
      <div id="account-panel" class="tools-popover account-popover disclosure-shell" aria-hidden="true">
        <div class="disclosure-clip" inert>
          <nav class="tools-links" aria-label="Sua conta">
            <a href="preferencias.html#minha-conta"><svg class="icon" aria-hidden="true"><use href="icons.svg#user"></use></svg>Minha conta</a>
            <button class="menu-logout" type="button" data-logout><svg class="icon" aria-hidden="true"><use href="icons.svg#logout"></use></svg>Sair da conta</button>
          </nav>
        </div>
      </div>
    </div>
  </div>
</header>
<div id="reconciliation-shell" class="disclosure-shell reconciliation-shell" aria-hidden="true">
<div class="disclosure-clip" inert>
<section id="tela-reconciliacao" class="recon-panel" aria-labelledby="reconciliation-title">

  <div class="diag-topo">
    <div>
      <h2 id="reconciliation-title">Reconciliação do Zabbix</h2>
      <p class="diag-sub">
        Estado do processo que recupera eventos perdidos e encerra incidentes resolvidos na origem.
        Esses encerramentos não são remediações executadas pelo Polaris.
      </p>
    </div>
    <div class="diag-acoes">
      <button id="btn-refresh-reconciliation" class="btn btn-secundario" type="button"><svg class="icon" aria-hidden="true"><use href="icons.svg#refresh"></use></svg>Atualizar</button>
      <button id="btn-fechar-reconciliacao" class="btn btn-secundario" type="button"><svg class="icon" aria-hidden="true"><use href="icons.svg#close"></use></svg>Fechar</button>
    </div>
  </div>

  <div id="recon-aviso" class="aviso oculto"></div>

  <div class="recon-resumo">
    <div class="recon-cartao"><span>Estado</span><strong id="recon-status">—</strong></div>
    <div class="recon-cartao"><span>Último ciclo</span><strong id="recon-ultima">—</strong></div>
    <div class="recon-cartao"><span>Intervalo</span><strong id="recon-intervalo">—</strong></div>
    <div class="recon-cartao"><span>Resultado do ciclo</span><strong id="recon-resultado">—</strong></div>
  </div>

  <div class="secao">
    <h3>Incidentes por estado</h3>
    <ul id="recon-contagens" class="recon-contagens"></ul>
  </div>

  <details class="recon-details">
    <summary>Ver atividade registrada <span id="recon-history-count" class="recon-count">—</span></summary>
    <p class="nota">Até 20 atividades significativas mais recentes, da mais nova para a mais antiga.
      Ciclos sem mudança apenas atualizam o horário do último ciclo; esta lista não é um log completo.</p>
    <ol id="recon-historico" class="recon-log" aria-label="Atividades registradas da reconciliação" tabindex="0"></ol>
  </details>

</section>
</div>
</div>
</div>`;
  function initials(name, login='') {
    const parts=String(name||login).trim().split(/\s+/u)
      .map(part=>part.match(/[\p{L}\p{N}]/u)?.[0]).filter(Boolean);
    if(!parts.length) return '?';
    return (parts[0]+(parts.length>1?parts.at(-1):'')).toLocaleUpperCase('pt-BR');
  }

  function bindAccountMenu(document, ui) {
    const menu=document.getElementById('account-menu');
    if(!menu) return;
    const trigger=document.getElementById('account-toggle');
    const panel=document.getElementById('account-panel');
    const close=()=>ui.setDisclosure(panel,trigger,false);
    const open=()=>{
      for(const [panelId,triggerId] of [['tools-panel','tools-toggle'],['server-panel','server-toggle'],['reconciliation-shell','estado-reconciliacao']]) {
        ui.setDisclosure(document.getElementById(panelId),document.getElementById(triggerId),false);
      }
      ui.setDisclosure(panel,trigger,true);
    };
    trigger.addEventListener('click',()=>{if(trigger.getAttribute('aria-expanded')==='true')close();else open();});
    trigger.addEventListener('keydown',event=>{
      if(event.key==='ArrowDown') { event.preventDefault();open();panel.querySelector('a').focus(); }
    });
    panel.querySelectorAll('a,button').forEach(action=>action.addEventListener('click',close));
    document.addEventListener('click',event=>{if(!menu.contains(event.target))close();});
    menu.addEventListener('focusout',event=>{if(!menu.contains(event.relatedTarget))close();});
    document.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&trigger.getAttribute('aria-expanded')==='true') {
        event.preventDefault();close();trigger.focus();
      }
    });
  }

  const api={markup,initials,bindAccountMenu};
  if(typeof module!=='undefined'&&module.exports) module.exports=api;
  root.PolarisHeader=api;
  if(!root.document) return;
  const mount=document.querySelector('[data-shared-header]');
  if(mount) mount.innerHTML=markup;
})(typeof window!=='undefined'?window:{});
