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
    const sources = {zabbix: "saved", ssh: "saved"};
    let generatedKey = false;
    let savedAt = {};
    const receipts = {};

    function locked() {
      location.href = '/login.html?next=/configuracao.html';
      $("setup-access").hidden = false;
      $("setup-workspace").hidden = true;
      for (const input of document.querySelectorAll('input[type="password"]')) input.value = "";
      savedAt = {};
      delete receipts.zabbix;
      delete receipts.ssh;
    }

    async function request(path, body) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 45000);
      const options = {method: body === undefined ? "GET" : "POST", cache: "no-store", signal: controller.signal};
      if (body !== undefined) {
        options.headers = {"Content-Type": "application/json", "X-Polaris-Setup": "1"};
        options.body = JSON.stringify(body);
      }
      try {
        const response = await fetch(`api/v1/instalacao/${path}`, options);
        const data = await response.json();
        if (!response.ok) {
          if (response.status === 401) locked();
          throw new Error(typeof data.mensagem === "string" ? data.mensagem : typeof data.detail === "string" ? data.detail : "Não foi possível concluir. Confira os campos e tente novamente.");
        }
        return data;
      } catch (error) {
        if (error.name === "AbortError") throw new Error("A consulta demorou demais. Confira a conexão e teste novamente antes de salvar.");
        throw error;
      } finally {
        clearTimeout(timer);
      }
    }

    function invalidate(stage) {
      delete receipts[stage];
      delete savedAt[stage];
      $("setup-save-" + stage).disabled = true;
      render();
    }

    async function loadConfiguration(from = "saved", stage = null) {
      const values = await request("configuracao?source=" + from);
      if (!stage || stage === "zabbix") {
      sources.zabbix = from;
      $("setup-zabbix-url").value = values.zabbix.url;
      $("setup-zabbix-mode").value = values.zabbix.mode;
      $("setup-zabbix-user").value = values.zabbix.username;
      for (const [id, available] of [["setup-zabbix-token", values.zabbix.token_available], ["setup-zabbix-password", values.zabbix.password_available], ["setup-webhook-token", values.zabbix.webhook_available]]) {
        $(id).value = "";
        $(id).placeholder = available ? "Disponível no servidor; mantenha vazio para reutilizar" : "Informe um novo valor";
      }
      }
      if (!stage || stage === "ssh") {
      sources.ssh = from;
      $("setup-ssh-host").value = values.ssh.host;
      $("setup-ssh-user").value = values.ssh.user;
      generatedKey = from !== "environment" && values.ssh.draft_key;
      $("setup-public-key").textContent = values.ssh.public_key || "Chave configurada no ambiente, ou ainda não gerada. A chave privada nunca é devolvida.";
      }
      $("setup-polling-interval").value = values.polling_interval ?? 30;
      if (from === "saved") savedAt = values.validated;
      else if (stage) delete savedAt[stage];
      else savedAt = {};
      delete receipts.zabbix;
      delete receipts.ssh;
      $("setup-save-zabbix").disabled = true;
      $("setup-save-ssh").disabled = true;
      updateMode();
      render();
    }

    function updateMode() {
      const token = $("setup-zabbix-mode").value === "token";
      $("setup-zabbix-token-fields").hidden = !token;
      $("setup-zabbix-password-fields").hidden = token;
    }

    async function refreshChecks() {
      const button = $("setup-check");
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
    }

    async function runForm(stage, task) {
      const target = $("setup-" + stage + "-message");
      target.textContent = "Verificando…";
      const form = $("setup-" + stage + "-form");
      const controls = [...form.querySelectorAll("button, input, select, textarea")];
      controls.forEach(button => { button.disabled = true; });
      try { await task(target); }
      catch (error) { target.textContent = error.message; }
      finally {
        controls.forEach(button => { button.disabled = false; });
        if (stage !== "polling") $("setup-save-" + stage).disabled = !receipts[stage] || Date.now() > receipts[stage].expires;
      }
    }


    function show(index, focus = true) {
      const model = navigationModel();
      if (index > current && !canVisit(index, model.stages)) {
        $("setup-feedback").textContent = "Conclua a configuração e a verificação da etapa anterior para continuar.";
        return;
      }
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
      render();
      if (focus) $("step-title-" + current).focus({preventScroll: true});
    }

    function navigationModel() {
      const model = evaluate(snapshot, confirmations);
      for (const [stage, index] of [["zabbix", 2], ["ssh", 3]]) {
        if (!savedAt[stage] || Date.now() - savedAt[stage] * 1000 >= MAX_AGE) model.stages[index] = "pendente";
      }
      model.count = model.stages.filter(state => state === "ok" || state === "manual").length;
      return model;
    }

    function render() {
      const model = navigationModel();
      buttons.forEach((button, i) => {
        button.dataset.state = model.stages[i];
        const allowed = canVisit(i, model.stages) || i <= current;
        button.disabled = !allowed;
        const label = LABELS[model.stages[i]];
        button.querySelector("small").textContent = label;
        button.setAttribute("aria-label", `Etapa ${i + 1}: ${button.querySelector("span:last-child").firstChild.textContent}. ${label}`);
      });
      $("setup-next").disabled = current === 5 || !canVisit(current + 1, model.stages);
      for (const stage of ["zabbix", "ssh"]) {
        if (receipts[stage] && Date.now() > receipts[stage].expires) {
          delete receipts[stage];
          $("setup-save-" + stage).disabled = true;
        }
      }
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
    document.querySelectorAll("[data-copy], [data-copy-field]").forEach(button => {
      button.addEventListener("click", async () => {
        const value = button.dataset.copyField ? $(button.dataset.copyField).value : $(button.dataset.copy).textContent;
        try {
          if (!value) throw new Error("Nenhum novo valor disponível para copiar.");
          await navigator.clipboard.writeText(value);
          $("setup-copy-feedback").textContent = "Copiado para a área de transferência.";
          window.PolarisToast(button.dataset.copyField ? 'Token copiado.' : button.dataset.copy === 'setup-public-key' ? 'Chave pública copiada.' : 'Comando copiado.');
          button.title = "Copiado";
        } catch { $("setup-copy-feedback").textContent = "Selecione o novo valor ou o comando e copie manualmente."; window.PolarisToast('Não foi possível copiar. Selecione e copie manualmente.'); }
        setTimeout(() => { button.title = "Copiar"; }, 2200);
      });
    });
    $("setup-logout").addEventListener("click", async () => {
      await window.PolarisSession.logout();
    });
    document.querySelectorAll("[data-load-env]").forEach(button => button.addEventListener("click", async () => {
      try { await loadConfiguration("environment", button.closest("form").id.includes("ssh") ? "ssh" : "zabbix"); $("setup-feedback").textContent = "Campos do ambiente carregados. Segredos permanecem no servidor; teste e salve para usar esta configuração."; }
      catch (error) { $("setup-feedback").textContent = error.message; }
    }));
    for (const stage of ["zabbix", "ssh"]) $("setup-" + stage + "-form").addEventListener("input", () => { invalidate(stage); updateMode(); });
    $("setup-zabbix-mode").addEventListener("change", () => { invalidate("zabbix"); updateMode(); });
    $("setup-generate-token").addEventListener("click", () => {
      const bytes = crypto.getRandomValues(new Uint8Array(32));
      $("setup-webhook-token").value = [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
      invalidate("zabbix");
      $("setup-zabbix-message").textContent = "Novo token gerado. Copie-o para o Media Type antes de salvar.";
    });
    $("setup-zabbix-form").addEventListener("submit", event => {
      event.preventDefault(); invalidate("zabbix");
      runForm("zabbix", async target => {
        const body = {source: sources.zabbix, url: $("setup-zabbix-url").value, mode: $("setup-zabbix-mode").value, username: $("setup-zabbix-user").value};
        for (const [key,id] of [["token","setup-zabbix-token"],["password","setup-zabbix-password"],["webhook_token","setup-webhook-token"]]) if ($(id).value) body[key] = $(id).value;
        const result = await request("zabbix/testar", body);
        receipts.zabbix = {id: result.receipt, expires: Date.now() + result.expires_in * 1000};
        target.textContent = result.message;
      });
    });
    $("setup-generate-key").addEventListener("click", () => runForm("ssh", async target => {
      invalidate("ssh");
      const result = await request("ssh/chave", {});
      $("setup-public-key").textContent = result.public_key;
      generatedKey = true;
      target.textContent = "Chave dedicada gerada. Autorize a chave pública no alvo antes de testar.";
    }));
    $("setup-inspect-host").addEventListener("click", () => runForm("ssh", async target => {
      const result = await request("ssh/identidade", {host: $("setup-ssh-host").value});
      $("setup-observed-fingerprint").textContent = "Observada pela rede: " + result.observed_fingerprint;
      target.textContent = result.message;
    }));
    $("setup-ssh-form").addEventListener("submit", event => {
      event.preventDefault(); invalidate("ssh");
      runForm("ssh", async target => {
        const result = await request("ssh/testar", {source: sources.ssh, host: $("setup-ssh-host").value, user: $("setup-ssh-user").value, expected_fingerprint: $("setup-ssh-fingerprint").value.trim(), generated_key: generatedKey});
        receipts.ssh = {id: result.receipt, expires: Date.now() + result.expires_in * 1000};
        target.textContent = result.message;
      });
    });
    for (const stage of ["zabbix", "ssh"]) $("setup-save-" + stage).addEventListener("click", () => runForm(stage, async target => {
      const receipt = receipts[stage];
      if (!receipt || Date.now() > receipt.expires) throw new Error("Teste novamente antes de salvar.");
      delete receipts[stage];
      const result = await request(stage + "/salvar", {receipt: receipt.id});
      await loadConfiguration();
      await refreshChecks();
      target.textContent = result.message;
    }));
    $("setup-polling-form").addEventListener("submit", event => {
      event.preventDefault();
      runForm("polling", async target => {
        const result = await request("reconciliacao", {interval: Number($("setup-polling-interval").value)});
        await refreshChecks();
        target.textContent = result.message;
      });
    });
    request("acesso").then(async status => {
      if (!status.secure_transport) {
        $("setup-access-message").textContent = "Use HTTPS ou o endereço local para acessar o assistente.";

      }
      if (status.authenticated) {
        await loadConfiguration();
        $("setup-access").hidden = true;
        $("setup-workspace").hidden = false;
      }
    }).catch(() => { $("setup-access-message").textContent = "Acesso indisponível. Confira o servidor e os volumes de configuração."; });
    $("setup-check").addEventListener("click", async () => {
      if (!$("setup-check").disabled) await refreshChecks();
    });
    setInterval(render, 15000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) render(); });
    show(0, false);
    render();
  }

  function canVisit(index, stages) {
    return index >= 0 && index <= 5 && stages.slice(0, index).every(state => state === "ok" || state === "manual");
  }

  const api = {checkState, evaluate, readChecks, canVisit};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else { root.PolarisSetup = api; initialize(); }
})(typeof window !== "undefined" ? window : globalThis);
