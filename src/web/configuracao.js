(function(root) {
  "use strict";
  const MAX_AGE = 5 * 60 * 1000;
  const LABELS = {ok: "Verificado", manual: "Confirmado por você", falha: "Requer correção",
    aviso: "Requer atenção", pendente: "Conferir etapa", unknown: "Ainda não verificado"};

  function checkState(checks, ids) {
    const states = ids.map(id => (Array.isArray(checks) ? checks : []).find(item => item?.id === id)?.estado);
    if (states.includes("falha")) return "falha";
    if (states.every(state => state === "ok")) return "ok";
    if (states.some(state => state === "aviso" || state === "nao_configurado")) return "aviso";
    return "unknown";
  }

  function evaluate(snapshot, confirmations = {}, now = Date.now()) {
    const age = now - snapshot.checkedAt;
    const fresh = Number.isFinite(age) && age >= 0 && age < MAX_AGE;
    const services = fresh ? checkState(snapshot.diagnostic?.verificacoes, ["banco", "migracoes", "base"]) : "unknown";
    const zabbix = fresh ? checkState(snapshot.connectivity?.verificacoes, ["zabbix"]) : "unknown";
    const ssh = fresh ? checkState(snapshot.diagnostic?.verificacoes, ["alvo"]) : "unknown";
    const cycle = snapshot.reconciliation;
    const cycleAge = now - Date.parse(cycle?.ultimo_ciclo?.ts_conclusao);
    const interval = Number(cycle?.intervalo_segundos);
    const recentCycle = Number.isFinite(cycleAge) && cycleAge >= -5000 &&
      interval > 0 && cycleAge <= Math.max(interval * 3, 60) * 1000;
    let reconciliation = "unknown";
    if (fresh && cycle) {
      reconciliation = cycle.status === "sucesso" && cycle.operacional === true &&
        cycle.habilitada === true && recentCycle ? "ok" : cycle.status === "erro" ? "falha" : "aviso";
    }
    const stages = [confirmations.environment ? "manual" : "pendente", services,
      zabbix === "ok" ? confirmations.zabbix ? "ok" : "pendente" : zabbix,
      ssh === "ok" ? confirmations.ssh ? "ok" : "pendente" : ssh,
      reconciliation, confirmations.delivery && confirmations.review ? "manual" : "pendente"];
    return {fresh, stages, count: stages.filter(state => state === "ok" || state === "manual").length,
      checks: {services, zabbix, ssh, reconciliation}};
  }

  async function readChecks(fetcher, signal) {
    const paths = ["diagnostico", "conectividade", "reconciliacao"];
    const results = await Promise.allSettled(paths.map(async path => {
      const response = await fetcher(`api/v1/${path}`, {method: "GET", cache: "no-store", signal});
      if (!response.ok) throw new Error("Consulta indisponível");
      return response.json();
    }));
    return {checkedAt: Date.now(), diagnostic: results[0].status === "fulfilled" ? results[0].value : null,
      connectivity: results[1].status === "fulfilled" ? results[1].value : null,
      reconciliation: results[2].status === "fulfilled" ? results[2].value : null,
      failed: results.filter(result => result.status === "rejected").length};
  }

  function initialize() {
    const $ = id => document.getElementById(id);
    const buttons = [...document.querySelectorAll("[data-step]")];
    const panels = [...document.querySelectorAll("[data-panel]")];
    const confirmations = {};
    let snapshot = {};
    let current = 0;

    function show(index, focus = true) {
      current = Math.min(5, Math.max(0, index));
      panels.forEach((panel, i) => {
        panel.hidden = i !== current;
        panel.classList.toggle("is-entering", i === current);
      });
      buttons.forEach((button, i) => {
        if (i === current) button.setAttribute("aria-current", "step");
        else button.removeAttribute("aria-current");
      });
      $("setup-position-label").textContent = `Etapa ${current + 1} de 6`;
      $("setup-previous").disabled = current === 0;
      $("setup-next").disabled = current === 5;
      if (focus) $("step-title-" + current).focus({preventScroll: true});
    }

    function render() {
      const model = evaluate(snapshot, confirmations);
      buttons.forEach((button, i) => {
        button.dataset.state = model.stages[i];
        const label = LABELS[model.stages[i]];
        button.querySelector("small").textContent = label;
        button.setAttribute("aria-label", `Etapa ${i + 1}: ${button.querySelector("span:last-child").firstChild.textContent}. ${label}`);
      });
      $("setup-count").textContent = `${model.count} de 6`;
      $("setup-progress").value = model.count;
      $("setup-progress").textContent = `${model.count} de 6`;
      const messages = {
        services: {ok: "Banco, esquema e base de conhecimento verificados.", falha: "Banco, esquema ou base requerem correção. Confira o estado dos serviços e as migrações.", aviso: "Há uma configuração incompleta. Consulte o diagnóstico no painel."},
        zabbix: {ok: "Consulta autenticada à API aceita. Confirme a integração manual abaixo.", falha: "A consulta autenticada falhou. Confira URL, credenciais e permissões no Zabbix.", aviso: "Configure URL e credenciais do Zabbix e verifique novamente."},
        ssh: {ok: "O alvo respondeu ao teste de conexão SSH. Confira identidade e permissões abaixo.", falha: "O acesso SSH falhou. Confira alvo, chave, permissões do arquivo e known_hosts.", aviso: "Alvo SSH não configurado. O modo sem alvo não valida remediação real."},
        reconciliation: {ok: "Ciclo recente da reconciliação concluído com sucesso.", falha: "A reconciliação registrou erro. Confira os logs e o acesso ao Zabbix.", aviso: "Reconciliação desativada, aguardando ou atrasada. Confira o processo e consulte novamente."}
      };
      for (const [name, state] of Object.entries(model.checks)) {
        const element = document.querySelector(`[data-result="${name}"]`);
        element.dataset.state = state;
        element.textContent = messages[name][state] || "Sem verificação atual disponível. Use Verificar conexões; se a consulta falhar, confira os serviços no terminal.";
      }
      $("setup-summary").textContent = model.count === 6
        ? "Conferência concluída nesta visita: conexões verificadas e etapas manuais confirmadas por você. A operação continua exigindo aprovação por incidente."
        : `${model.count} de 6 etapas conferidas. Revise as pendências e confirme as etapas manuais antes de operar.`;
      if (snapshot.checkedAt && !model.fresh) {
        $("setup-checked-at").textContent = "A verificação perdeu a validade. Consulte novamente para conferir o estado atual.";
      }
    }

    buttons.forEach((button, i) => {
      button.addEventListener("click", () => show(i));
      button.addEventListener("keydown", event => {
        const delta = {ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1}[event.key];
        if (!delta) return;
        event.preventDefault();
        const index = (i + delta + buttons.length) % buttons.length;
        show(index, false);
        buttons[index].focus();
      });
    });
    $("setup-previous").addEventListener("click", () => show(current - 1));
    $("setup-next").addEventListener("click", () => show(current + 1));
    document.querySelectorAll("[data-confirm]").forEach(input => {
      input.checked = false;
      input.addEventListener("change", () => { confirmations[input.dataset.confirm] = input.checked; render(); });
    });
    document.querySelectorAll("[data-copy]").forEach(button => {
      button.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText($(button.dataset.copy).textContent);
          button.textContent = "Copiado";
        } catch { button.textContent = "Selecione o texto e copie"; }
        setTimeout(() => { button.textContent = "Copiar comandos"; }, 2200);
      });
    });
    $("setup-check").addEventListener("click", async () => {
      const button = $("setup-check");
      if (button.disabled) return;
      button.disabled = true;
      $("setup-content").setAttribute("aria-busy", "true");
      $("setup-feedback").textContent = "Consultando as conexões…";
      snapshot = {};
      render();
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 45000);
      try {
        snapshot = await readChecks(window.fetch.bind(window), controller.signal);
        render();
        $("setup-feedback").textContent = snapshot.failed
          ? "Parte das consultas não respondeu. Os resultados indisponíveis permanecem pendentes."
          : "Consulta concluída. Confira o resultado de cada etapa.";
        $("setup-checked-at").textContent = `Consultado às ${new Date(snapshot.checkedAt).toLocaleTimeString("pt-BR")}. Validade: 5 minutos; uma mudança exige nova consulta.`;
      } finally {
        clearTimeout(timer);
        button.disabled = false;
        $("setup-content").setAttribute("aria-busy", "false");
      }
    });
    setInterval(render, 15000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) render(); });
    show(0, false);
    render();
  }

  const api = {checkState, evaluate, readChecks};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else { root.PolarisSetup = api; initialize(); }
})(typeof window !== "undefined" ? window : globalThis);
