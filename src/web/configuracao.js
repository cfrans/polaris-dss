(function(root) {
  "use strict";
  const MAX_AGE = 5 * 60 * 1000;
  const AUTO_REFRESH_MARGIN = 15 * 1000;
  const CONFIRMATIONS_KEY = "polaris.setup.confirmations.v1";
  const CONFIRMATION_FIELDS = ["environment", "zabbix", "ssh", "delivery", "review"];
  const LABELS = {ok: "Verificado", manual: "Confirmado por você", falha: "Requer correção",
    aviso: "Requer atenção", pendente: "Conferir etapa", unknown: "Ainda não verificado"};
  const SERVICE_USER = /^[a-z_][a-z0-9_-]{0,31}$/;
  const PUBLIC_KEY = /^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]+( [^'\n\r]*)?$/;
  const AGENT_HOST = /^[A-Za-z0-9._-]{1,128}$/;
  const ZABBIX_RELEASE = "zabbix-release_latest_7.0+ubuntu24.04_all.deb";

  function checkState(checks, ids) {
    const states = ids.map(id => (Array.isArray(checks) ? checks : []).find(item => item?.id === id)?.estado);
    if (states.includes("falha")) return "falha";
    if (states.every(state => state === "ok")) return "ok";
    if (states.some(state => state === "aviso" || state === "nao_configurado")) return "aviso";
    return "unknown";
  }

  function evaluate(snapshot, confirmations = {}, now = Date.now(), savedAt = null) {
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
      reconciliation,
      confirmations.delivery && confirmations.review && snapshot.science?.acknowledged === true ? "manual" : "pendente"];
    if (savedAt) {
      for (const [stage, index] of [["zabbix", 2], ["ssh", 3]]) {
        if (!savedAt[stage]) stages[index] = "pendente";
      }
    }
    return {fresh, stages, count: stages.filter(state => state === "ok" || state === "manual").length,
      checks: {services, zabbix, ssh, reconciliation}};
  }

  /* Manual confirmations belong to one account in one browser and to one vault revision. */
  function confirmationsKey(user) {
    return user ? `${CONFIRMATIONS_KEY}:${user}` : CONFIRMATIONS_KEY;
  }

  function readStoredConfirmations(storage, expectedRevision, user = "") {
    try {
      const parsed = JSON.parse(storage?.getItem(confirmationsKey(user)) || "null");
      if (!parsed || typeof parsed !== "object") return {};
      if (expectedRevision && parsed.revision && parsed.revision !== expectedRevision) return {};
      const source = parsed.confirmations && typeof parsed.confirmations === "object" ? parsed.confirmations : parsed;
      const result = {};
      for (const field of CONFIRMATION_FIELDS) {
        if (source[field] === true) result[field] = true;
      }
      return result;
    } catch {
      return {};
    }
  }

  function writeStoredConfirmations(storage, revision, confirmations, user = "") {
    try {
      const clean = {};
      for (const field of CONFIRMATION_FIELDS) {
        if (confirmations[field] === true) clean[field] = true;
      }
      storage?.setItem(confirmationsKey(user), JSON.stringify({revision: revision || null, confirmations: clean}));
    } catch {
      /* Funciona apenas em memória se o armazenamento estiver indisponível. */
    }
  }

  function furthestStep(stages) {
    let step = 0;
    for (let index = 1; index <= 5; index += 1) {
      if (canVisit(index, stages)) step = index;
      else break;
    }
    return step;
  }

  /* Copyable commands. Values typed in the page only enter them after strict validation,
     so a pasted command never carries quotes or shell syntax from a form field. */
  function targetCommands(user, publicKey) {
    const account = SERVICE_USER.test(user || "") ? user : "<usuario>";
    const key = PUBLIC_KEY.test((publicKey || "").trim()) ? publicKey.trim() : "<cole aqui a chave pública gerada acima>";
    const home = `/home/${account}/.ssh`;
    return [
      `sudo adduser --disabled-password --gecos '' ${account}`,
      `sudo install -d -m 0700 -o ${account} -g ${account} ${home}`,
      `echo '${key}' | sudo tee -a ${home}/authorized_keys > /dev/null`,
      `sudo chown ${account}:${account} ${home}/authorized_keys`,
      `sudo chmod 0600 ${home}/authorized_keys`,
      `echo '${account} ALL=(root) NOPASSWD: /usr/bin/timeout' | sudo tee /etc/sudoers.d/${account} > /dev/null`,
      `sudo chmod 0440 /etc/sudoers.d/${account}`,
      `sudo visudo -cf /etc/sudoers.d/${account}`,
    ].join("\n");
  }

  function hostFromUrl(url) {
    try {
      const host = new URL(url).hostname;
      return /^[A-Za-z0-9.:[\]-]+$/.test(host) ? host.replace(/^\[|\]$/g, "") : "";
    } catch {
      return "";
    }
  }

  function agentCommands(zabbixUrl, hostName) {
    const server = hostFromUrl(zabbixUrl) || "<IP-do-Zabbix>";
    const name = AGENT_HOST.test(hostName || "") ? hostName : "<nome-do-host>";
    return [
      `wget https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/${ZABBIX_RELEASE}`,
      `sudo dpkg -i ${ZABBIX_RELEASE}`,
      "sudo apt update",
      "sudo apt install -y zabbix-agent2",
      `sudo sed -i -e 's/^Server=.*/Server=${server}/' -e 's/^ServerActive=.*/ServerActive=${server}/' -e 's/^Hostname=.*/Hostname=${name}/' /etc/zabbix/zabbix_agent2.conf`,
      "sudo systemctl enable --now zabbix-agent2",
      "sudo systemctl restart zabbix-agent2",
    ].join("\n");
  }

  function webhookUrl(location) {
    const local = ["localhost", "127.0.0.1", "[::1]", "::1"].includes(location.hostname);
    const port = location.port ? `:${location.port}` : "";
    return local ? `http://IP-do-servidor-Polaris${port}/webhook/zabbix`
      : `${location.protocol}//${location.hostname}${port}/webhook/zabbix`;
  }

  /* Zabbix 7.0 action.create: condition types 25 tag name, 26 tag value (value2 = tag),
     13 host template (value = templateid), 3 event name; evaltype 3 = custom expression. */
  function actionPayload() {
    return {jsonrpc: "2.0", method: "action.create", id: 1, params: {
      name: "Polaris DSS — encaminhar eventos", eventsource: 0, status: 0,
      filter: {evaltype: 3, formula: "(A and B) or (C and D)", conditions: [
        {conditiontype: 25, operator: 0, value: "polaris", formulaid: "A"},
        {conditiontype: 26, operator: 0, value2: "polaris", value: "enabled", formulaid: "B"},
        {conditiontype: 13, operator: 0, value: "<templateid de Linux by Zabbix agent>", formulaid: "C"},
        {conditiontype: 3, operator: 2, value: "Linux: High CPU utilization", formulaid: "D"}]},
      operations: [{operationtype: 0,
        opmessage: {default_msg: 1, mediatypeid: "<mediatypeid de Polaris DSS>"},
        opmessage_usr: [{userid: "<userid do destinatário>"}]}]}};
  }

  function actionCurl(zabbixUrl) {
    const url = hostFromUrl(zabbixUrl) ? zabbixUrl : "<URL-da-API-do-Zabbix>";
    return ["export ZABBIX_ADMIN_TOKEN='<token de API com permissão de escrita>'",
      "curl -s -X POST -H 'Content-Type: application/json-rpc' \\",
      "  -H \"Authorization: Bearer $ZABBIX_ADMIN_TOKEN\" \\",
      `  --data @polaris-action.json ${url}`].join("\n");
  }

  async function readChecks(fetcher, signal) {
    const paths = ["diagnostico", "conectividade", "reconciliacao", "auth/ciencia"];
    const results = await Promise.allSettled(paths.map(async path => {
      const response = await fetcher(`api/v1/${path}`, {method: "GET", cache: "no-store", signal});
      if (!response.ok) throw new Error("Consulta indisponível");
      return response.json();
    }));
    return {checkedAt: Date.now(), diagnostic: results[0].status === "fulfilled" ? results[0].value : null,
      connectivity: results[1].status === "fulfilled" ? results[1].value : null,
      reconciliation: results[2].status === "fulfilled" ? results[2].value : null,
      science: results[3].status === "fulfilled" ? results[3].value : null,
      failed: results.filter(result => result.status === "rejected").length};
  }

  function initialize() {
    const $ = id => document.getElementById(id);
    const buttons = [...document.querySelectorAll("[data-step]")];
    const panels = [...document.querySelectorAll("[data-panel]")];
    let confirmations = {};
    let currentRevision = null;
    let currentUser = "";
    let snapshot = {};
    let current = 0;
    let refreshing = false;
    let savedZabbixUrl = "";
    const sources = {zabbix: "saved", ssh: "saved"};
    let generatedKey = false;
    let savedAt = {};
    const receipts = {};

    function syncConfirmInputs() {
      document.querySelectorAll("[data-confirm]").forEach(input => {
        input.checked = Boolean(confirmations[input.dataset.confirm]);
      });
    }

    function storeConfirmations() {
      writeStoredConfirmations(window.localStorage, currentRevision, confirmations, currentUser);
    }

    /* Every vault write returns its new revision; keeping it avoids discarding confirmations
       on the next visit (the polling interval and draft keys also change the revision). */
    function adoptRevision(revision) {
      if (!revision) return;
      currentRevision = revision;
      storeConfirmations();
    }

    function setStatus(element, state, text) {
      element.dataset.state = state;
      if (text !== undefined) element.textContent = text;
    }

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

    function clearReceipt(stage) {
      delete receipts[stage];
      $("setup-save-" + stage).disabled = true;
      render();
    }

    function invalidate(stage) {
      delete savedAt[stage];
      clearReceipt(stage);
    }

    function updateCommands() {
      $("target-command").textContent = targetCommands($("setup-ssh-user").value.trim(), $("setup-public-key").textContent);
      $("agent-command").textContent = agentCommands(savedZabbixUrl, $("setup-server-host").value.trim());
      $("action-curl").textContent = actionCurl(savedZabbixUrl);
    }

    async function loadConfiguration(from = "saved", stage = null) {
      const values = await request("configuracao?source=" + from);
      if (from === "saved") {
        if (!currentRevision) {
          confirmations = readStoredConfirmations(window.localStorage, values.revision, currentUser);
          syncConfirmInputs();
        }
        currentRevision = values.revision || null;
        storeConfirmations();
        savedZabbixUrl = values.zabbix.url || "";
        $("setup-server-host").value = values.server_host || "";
      }
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
      showPollingInForce(values.polling_interval);
      if (from === "saved") savedAt = values.validated || {};
      else if (stage) delete savedAt[stage];
      else savedAt = {};
      delete receipts.zabbix;
      delete receipts.ssh;
      $("setup-save-zabbix").disabled = true;
      $("setup-save-ssh").disabled = true;
      updateMode();
      updateCommands();
      render();
    }

    function showPollingInForce(interval) {
      const seconds = Number(interval);
      $("setup-polling-current").textContent = !Number.isFinite(seconds) ? ""
        : seconds > 0 ? `Em vigor: consulta a cada ${seconds} segundos. Salve apenas se quiser mudar o intervalo.`
          : "Em vigor: consultas pausadas. Informe um intervalo e salve para ativar.";
    }

    /* A first cycle can finish after the page loaded; follow it instead of asking for a new save. */
    async function followReconciliation() {
      if (refreshing || document.hidden || $("setup-workspace").hidden || current < 4 || !snapshot.checkedAt) return;
      if (navigationModel().checks.reconciliation === "ok") return;
      try {
        const response = await fetch("api/v1/reconciliacao", {method: "GET", cache: "no-store"});
        if (!response.ok) return;
        snapshot.reconciliation = await response.json();
        if (Date.now() - snapshot.checkedAt >= MAX_AGE - AUTO_REFRESH_MARGIN) await refreshChecks();
        else render();
      } catch {
        /* Próxima tentativa no intervalo seguinte. */
      }
    }

    function renderScience() {
      const science = snapshot.science;
      const status = $("setup-science-status");
      if (!science) {
        setStatus(status, "unknown", "Ciência ainda não consultada. Use Verificar conexões.");
      } else if (science.acknowledged) {
        const at = science.at ? ` em ${window.PolarisUI.formatTime(Date.parse(science.at))}` : "";
        setStatus(status, "ok", `Ciência registrada na sua conta${at}, para a versão atual dos scripts.`);
        $("setup-science-open").lastChild.textContent = "Ler os scripts novamente";
      } else {
        setStatus(status, "aviso", "Ainda não registrada para a sua conta nesta versão dos scripts.");
      }
    }

    const science = {catalog: null, index: 0};
    function showScript(index) {
      const scripts = science.catalog?.scripts || [];
      if (!scripts.length) return;
      science.index = (index + scripts.length) % scripts.length;
      const script = scripts[science.index];
      const description = window.PolarisScriptViewer.describeScript(script.nome);
      $("science-name").textContent = script.nome;
      $("science-count").textContent = `${science.index + 1} de ${scripts.length}`;
      $("science-purpose").textContent = `${description.purpose} Efeitos: ${description.effect}`;
      window.PolarisScriptViewer.renderScript($("science-code"), script.conteudo, true);
      $("science-code").scrollTop = 0;
    }

    async function openScience() {
      const dialog = $("setup-science");
      $("science-error").hidden = true;
      $("science-confirm").disabled = true;
      if (!dialog.open) dialog.showModal();
      try {
        const response = await fetch("api/v1/scripts-padrao", {cache: "no-store"});
        if (!response.ok) throw new Error("Não foi possível carregar os scripts.");
        science.catalog = await response.json();
        showScript(0);
        $("science-confirm").disabled = false;
      } catch (error) {
        $("science-error").textContent = error.message;
        $("science-error").hidden = false;
      }
    }

    async function confirmScience() {
      if (!science.catalog) return;
      $("science-confirm").disabled = true;
      try {
        const response = await fetch("api/v1/auth/ciencia", {method: "POST", cache: "no-store",
          headers: {"Content-Type": "application/json", "X-Polaris-Auth": "1"},
          body: JSON.stringify({version: science.catalog.versao})});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.mensagem || "Não foi possível registrar a ciência.");
        snapshot.science = {version: science.catalog.versao, acknowledged: true, at: new Date().toISOString()};
        $("setup-science").close();
        render();
        window.PolarisToast?.("Ciência registrada na sua conta.");
      } catch (error) {
        $("science-error").textContent = error.message;
        $("science-error").hidden = false;
        $("science-confirm").disabled = false;
      }
    }

    function updateMode() {
      const token = $("setup-zabbix-mode").value === "token";
      $("setup-zabbix-token-fields").hidden = !token;
      $("setup-zabbix-password-fields").hidden = token;
    }

    async function refreshChecks() {
      if (refreshing) return;
      refreshing = true;
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
        $("setup-checked-at").textContent = `Consultado às ${window.PolarisUI.formatTime(snapshot.checkedAt)}. Validade de 5 minutos, renovada automaticamente com a página aberta.`;
      } finally {
        clearTimeout(timer);
        refreshing = false;
        button.disabled = false;
        $("setup-content").setAttribute("aria-busy", "false");
      }
    }

    function refreshIfStale() {
      if (!snapshot.checkedAt || refreshing || document.hidden || $("setup-workspace").hidden) return;
      if (Date.now() - snapshot.checkedAt >= MAX_AGE - AUTO_REFRESH_MARGIN) refreshChecks();
    }

    async function runForm(stage, task) {
      const target = $("setup-" + stage + "-message");
      setStatus(target, "busy", "Verificando…");
      const form = $("setup-" + stage + "-form");
      const controls = [...form.querySelectorAll("button, input, select, textarea")];
      controls.forEach(control => { control.disabled = true; });
      try {
        await task(target);
        if (target.dataset.state === "busy") target.dataset.state = "ok";
      } catch (error) { setStatus(target, "falha", error.message); }
      finally {
        controls.forEach(control => { control.disabled = false; });
        if (stage === "zabbix" || stage === "ssh") $("setup-save-" + stage).disabled = !receipts[stage] || Date.now() > receipts[stage].expires;
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
      return evaluate(snapshot, confirmations, Date.now(), savedAt);
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
      const isLastStep = current === 5;
      $("setup-next").textContent = isLastStep ? "Concluir e abrir painel" : "Continuar";
      $("setup-next").disabled = isLastStep ? model.count < 6 : !canVisit(current + 1, model.stages);
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
      $("setup-summary").dataset.state = model.count === 6 ? "ok" : "pendente";
      $("setup-summary").textContent = model.count === 6
        ? "Conferência concluída: conexões verificadas e etapas manuais confirmadas por você. A operação continua exigindo aprovação por incidente."
        : `${model.count} de 6 etapas conferidas. Revise as pendências e confirme as etapas manuais antes de concluir.`;
      renderScience();
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
    $("setup-next").addEventListener("click", () => {
      if (current === 5) {
        const model = navigationModel();
        if (model.count === 6) {
          storeConfirmations();
          location.href = "./";
        }
        return;
      }
      show(current + 1);
    });
    document.querySelectorAll("[data-confirm]").forEach(input => {
      input.checked = false;
      input.addEventListener("change", () => {
        confirmations[input.dataset.confirm] = input.checked;
        storeConfirmations();
        render();
      });
    });
    window.PolarisCopy.bind(document);
    $("webhook-url").textContent = webhookUrl(location);
    $("action-json").textContent = JSON.stringify(actionPayload(), null, 2);
    updateCommands();
    document.querySelectorAll("[data-load-env]").forEach(button => button.addEventListener("click", async () => {
      try { await loadConfiguration("environment", button.closest("form").id.includes("ssh") ? "ssh" : "zabbix"); $("setup-feedback").textContent = "Campos do ambiente carregados. Segredos permanecem no servidor; teste e salve para usar esta configuração."; }
      catch (error) { $("setup-feedback").textContent = error.message; }
    }));
    for (const stage of ["zabbix", "ssh"]) $("setup-" + stage + "-form").addEventListener("input", event => {
      invalidate(stage);
      updateMode();
      if (stage === "ssh" && event.target.id === "setup-ssh-user") updateCommands();
    });
    $("setup-server-host").addEventListener("input", updateCommands);
    $("setup-zabbix-mode").addEventListener("change", () => { invalidate("zabbix"); updateMode(); });
    $("setup-generate-token").addEventListener("click", () => {
      const bytes = crypto.getRandomValues(new Uint8Array(32));
      $("setup-webhook-token").value = [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
      invalidate("zabbix");
      setStatus($("setup-zabbix-message"), "aviso", "Novo token gerado. Copie-o para o Media Type antes de salvar.");
    });
    $("setup-zabbix-form").addEventListener("submit", event => {
      event.preventDefault(); clearReceipt("zabbix");
      runForm("zabbix", async target => {
        const body = {source: sources.zabbix, url: $("setup-zabbix-url").value, mode: $("setup-zabbix-mode").value, username: $("setup-zabbix-user").value};
        for (const [key,id] of [["token","setup-zabbix-token"],["password","setup-zabbix-password"],["webhook_token","setup-webhook-token"]]) if ($(id).value) body[key] = $(id).value;
        try {
          const result = await request("zabbix/testar", body);
          receipts.zabbix = {id: result.receipt, expires: Date.now() + result.expires_in * 1000};
          // The server reports the endpoint that answered (root or /zabbix); show it as saved.
          if (result.url) $("setup-zabbix-url").value = result.url;
          if (savedAt.zabbix) await refreshChecks();
          setStatus(target, "ok", result.message);
        } catch (error) {
          invalidate("zabbix");
          throw error;
        }
      });
    });
    $("setup-generate-key").addEventListener("click", () => runForm("ssh", async target => {
      invalidate("ssh");
      const result = await request("ssh/chave", {});
      adoptRevision(result.revision);
      $("setup-public-key").textContent = result.public_key;
      generatedKey = true;
      updateCommands();
      setStatus(target, "ok", "Chave dedicada gerada. Autorize a chave pública no alvo antes de testar.");
    }));
    $("setup-inspect-host").addEventListener("click", () => runForm("ssh", async target => {
      const result = await request("ssh/identidade", {host: $("setup-ssh-host").value});
      $("setup-observed-fingerprint").textContent = "Observada pela rede: " + result.observed_fingerprint;
      setStatus(target, "aviso", result.message);
    }));
    $("setup-ssh-form").addEventListener("submit", event => {
      event.preventDefault(); clearReceipt("ssh");
      runForm("ssh", async target => {
        try {
          const result = await request("ssh/testar", {source: sources.ssh, host: $("setup-ssh-host").value, user: $("setup-ssh-user").value, expected_fingerprint: $("setup-ssh-fingerprint").value.trim(), generated_key: generatedKey});
          receipts.ssh = {id: result.receipt, expires: Date.now() + result.expires_in * 1000};
          if (savedAt.ssh) await refreshChecks();
          setStatus(target, "ok", result.message);
        } catch (error) {
          invalidate("ssh");
          throw error;
        }
      });
    });
    for (const stage of ["zabbix", "ssh"]) $("setup-save-" + stage).addEventListener("click", () => runForm(stage, async target => {
      const receipt = receipts[stage];
      if (!receipt || Date.now() > receipt.expires) throw new Error("Teste novamente antes de salvar.");
      delete receipts[stage];
      const result = await request(stage + "/salvar", {receipt: receipt.id});
      await loadConfiguration();
      await refreshChecks();
      setStatus(target, "ok", result.message);
    }));
    $("setup-polling-form").addEventListener("submit", event => {
      event.preventDefault();
      runForm("polling", async target => {
        const result = await request("reconciliacao", {interval: Number($("setup-polling-interval").value)});
        adoptRevision(result.revision);
        showPollingInForce(Number($("setup-polling-interval").value));
        await refreshChecks();
        setStatus(target, "ok", result.message);
      });
    });
    $("setup-server-form").addEventListener("submit", event => {
      event.preventDefault();
      runForm("server", async target => {
        const result = await request("servidor", {host: $("setup-server-host").value.trim()});
        adoptRevision(result.revision);
        setStatus(target, result.state === "ok" || result.state === "nao_configurado" ? "ok" : "aviso", result.message);
      });
    });
    request("acesso").then(async status => {
      if (!status.secure_transport) {
        $("setup-access-message").textContent = "Abra o assistente por HTTPS, pelo túnel SSH ou por um navegador pareado.";
      }
      if (status.authenticated) {
        const user = await window.PolarisSession.ready;
        currentUser = user?.login || "";
        await loadConfiguration();
        $("setup-access").hidden = true;
        $("setup-workspace").hidden = false;
        await refreshChecks();
        const targetStep = furthestStep(navigationModel().stages);
        if (targetStep > 0) show(targetStep, false);
      }
    }).catch(() => { $("setup-access-message").textContent = "Acesso indisponível. Confira o servidor e os volumes de configuração."; });
    $("setup-check").addEventListener("click", async () => {
      if (!$("setup-check").disabled) await refreshChecks();
    });
    $("setup-science-open").addEventListener("click", openScience);
    $("science-confirm").addEventListener("click", confirmScience);
    $("science-previous").addEventListener("click", () => showScript(science.index - 1));
    $("science-next").addEventListener("click", () => showScript(science.index + 1));
    document.querySelectorAll("[data-science-close]").forEach(button => button.addEventListener("click", () => $("setup-science").close()));
    setInterval(() => { render(); refreshIfStale(); }, 15000);
    setInterval(followReconciliation, 10000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) { render(); refreshIfStale(); } });
    show(0, false);
    render();
  }

  function canVisit(index, stages) {
    return index >= 0 && index <= 5 && stages.slice(0, index).every(state => state === "ok" || state === "manual");
  }

  const api = {checkState, evaluate, readChecks, canVisit, readStoredConfirmations, writeStoredConfirmations,
    furthestStep, confirmationsKey, targetCommands, agentCommands, webhookUrl, actionPayload, actionCurl};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else { root.PolarisSetup = api; initialize(); }
})(typeof window !== "undefined" ? window : globalThis);
