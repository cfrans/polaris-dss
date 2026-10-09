/* Laboratory command drafting. No injection, approval or round write is sent over HTTP. */
(function (root) {
  "use strict";
  const SCENARIOS = ["service_down", "cpu_high", "disk_full"];
  const shellQuote = (value) => "'" + String(value).replace(/'/g, "'\"'\"'") + "'";
  const positive = (value, maximum = Number.MAX_SAFE_INTEGER) => /^\d+$/.test(String(value))
    && Number(value) > 0 && Number(value) <= maximum;
  const text = (value, maximum) => typeof value === "string" && value.trim()
    && !/[\x00\r\n]/.test(value) && (!maximum || value.length <= maximum);

  function command(action, options = {}) {
    return "python3 experiment/lab.py " + action + Object.entries(options)
      .map(([key, value]) => ` --${key} ${shellQuote(value)}`).join("");
  }

  function draft(config) {
    if (!SCENARIOS.includes(config.scenario) || !["baseline", "hitl"].includes(config.arm)) {
      throw new Error("Cenário ou braço inválido.");
    }
    const prefix = `experiment/evidence/${config.session}`;
    const adminValid = text(config.adminUser) && text(config.adminKey);
    const admin = {"admin-user": config.adminUser, "admin-key-file": config.adminKey};
    const metadataValid = text(config.operator, 64) && text(config.version, 32)
      && /^[0-9a-f]{40}$/.test(config.sha) && positive(config.repetition, 32767)
      && positive(config.timeout, config.scenario === "cpu_high" ? 1800 : Number.MAX_SAFE_INTEGER);
    const pathsValid = /^[a-zA-Z0-9_-]+$/.test(config.session);
    const runValid = positive(config.runId);
    const closeValid = positive(config.closeId);
    return {
      inspect: command("inspect"),
      prepare: adminValid && config.scenario === "disk_full"
        ? command("prepare", {scenario: config.scenario, ...admin}) : null,
      check: adminValid ? command("check", {scenario: config.scenario, ...admin}) : null,
      run: adminValid && metadataValid ? command("run", {scenario: config.scenario, arm: config.arm,
        repetition: config.repetition, operator: config.operator, "system-version": config.version,
        "commit-sha": config.sha, timeout: config.timeout, ...admin}) : null,
      link: config.arm === "hitl" && runValid && positive(config.incidentId) && /^\d+$/.test(config.eventId)
        ? command("link", {"run-id": config.runId, "incident-id": config.incidentId, "event-id": config.eventId}) : null,
      assess: runValid && pathsValid ? command("assess", {"run-id": config.runId,
        "record-file": `${prefix}/rodada-${config.runId}-avaliacao.json`}) : null,
      discard: closeValid && text(config.reason) ? command("discard", {"run-id": config.closeId, reason: config.reason}) : null,
      backup: closeValid && pathsValid ? command("backup", {output: `${prefix}/rodada-${config.closeId}.dump`}) : null,
      report: closeValid && pathsValid ? command("report", {output: `${prefix}/rodada-${config.closeId}-relatorio`, kind: "collected"}) : null,
      reset: closeValid && adminValid ? command("reset", {"run-id": config.closeId, ...admin}) : null,
      assessmentPath: pathsValid && runValid ? `${prefix}/rodada-${config.runId}-avaliacao.json` : null,
    };
  }

  function assessment(values) {
    if (!/^\d+$/.test(String(values.steps)) || Number(values.steps) > 32767
      || !["true", "false"].includes(values.resolved) || !values.observations.trim()) {
      throw new Error("Preencha os passos observados, o resultado e as observações antes de baixar.");
    }
    return {passos_manuais: Number(values.steps), comandos_usados: values.commands,
      resolvido: values.resolved === "true", observacoes: values.observations};
  }

  const api = {shellQuote, command, draft, assessment};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.PolarisLab = api;
  if (!root.document) return;
  const $ = (id) => document.getElementById("lab-" + id);
  const fields = ["scenario", "arm", "repetition", "session", "operator", "version", "sha", "timeout",
    "admin-user", "admin-key", "run-id", "incident-id", "event-id", "close-id", "reason"];

  function readConfig() {
    return Object.fromEntries(fields.map((name) => [name.replace(/-([a-z])/g, (_, char) => char.toUpperCase()), $(name).value]));
  }

  function showCommand(container, title, value, note, missing) {
    const card = document.createElement("article");
    card.className = "lab-command";
    const heading = document.createElement("div");
    heading.className = "lab-command-head";
    const label = document.createElement("h3");
    label.textContent = title;
    heading.appendChild(label);
    card.appendChild(heading);
    if (value) {
      const button = document.createElement("button");
      button.className = "btn btn-secundario";
      button.type = "button";
      button.textContent = "Copiar comando";
      button.setAttribute("aria-label", `Copiar: ${title}`);
      const pre = document.createElement("pre");
      pre.textContent = value;
      button.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(value);
          $("message").textContent = "Comando copiado. Execute no terminal do servidor quando chegar a esta etapa.";
        } catch {
          const range = document.createRange();
          range.selectNodeContents(pre);
          const selection = root.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          $("message").textContent = "Use Ctrl+C ou ⌘C para copiar o comando selecionado.";
        }
      });
      heading.appendChild(button);
      card.appendChild(pre);
    }
    const description = document.createElement("p");
    description.className = "nota";
    description.textContent = value ? note : missing;
    card.appendChild(description);
    container.appendChild(card);
  }

  const RUNBOOKS = {
    service_down: ["No Zabbix, abra o alerta real e identifique o host e a condição.",
      "Abra uma sessão SSH administrativa. Confira systemctl status nginx --no-pager; consulte journalctl -u nginx -n 30 --no-pager se necessário.",
      "Após confirmar o diagnóstico, execute systemctl restart nginx como administrador (sudo se a conta exigir).",
      "Confira systemctl is-active nginx. Aguarde a medição independente; revise diagnóstico e efeitos colaterais."],
    cpu_high: ["No Zabbix, abra o alerta real e identifique o host.",
      "Abra SSH administrativo e leia a segunda amostra de top -bn2 -d 1 -o %CPU.",
      "Confira o PID com ps -p <pid> -o pid,comm,args -ww; confirme vínculo com polaris-experiment-cpu.service e processo permitido.",
      "Envie TERM somente ao PID confirmado. Se necessário, após dez segundos, envie KILL ao mesmo candidato e registre a ação adicional.",
      "Confira CPU, medição independente e efeitos colaterais. A expiração da carga não prova remediação pelo operador."],
    disk_full: ["No Zabbix, abra o alerta real e identifique o host e o volume.",
      "Abra SSH administrativo. Confira df -h /mnt/polaris_test, arquivos gzip e datas; confirme que os dados são descartáveis.",
      "Envie manualmente os bytes congelados de src/scripts/disk_cleanup.sh por SSH stdin com o único argumento /mnt/polaris_test, conforme o roteiro.",
      "Confira df -h /mnt/polaris_test e aguarde o observador. Inspecione os efeitos do logrotate global antes de avaliar."],
  };

  function render() {
    const config = readConfig();
    const commands = draft(config);
    document.querySelectorAll("[data-hitl]").forEach((element) => element.classList.toggle("oculto", config.arm !== "hitl"));
    ["prepare-commands", "run-command", "record-commands", "close-commands"].forEach((name) => $(name).replaceChildren());
    showCommand($("prepare-commands"), "Inspecionar a implantação", commands.inspect,
      "Execute na raiz do checkout no servidor. Confira migrações, imagem e diagnóstico; histórico de confiança deve estar desligado para as condições controladas.");
    if (config.scenario === "disk_full") showCommand($("prepare-commands"), "Preparar os dados descartáveis de disco", commands.prepare,
      "Cria gzip no volume isolado de aproximadamente 2 GB; não monta nem formata. Faça antes do checklist global para R001.", "Preencha o usuário e o caminho da chave administrativa.");
    showCommand($("prepare-commands"), "Conferir os três cenários", commands.check,
      "Modo de inspeção: não injeta, não apaga nem recupera. Exige estado inicial limpo e nenhuma rodada/incidente aberto.", "Preencha o usuário e o caminho da chave administrativa.");
    showCommand($("run-command"), "Injetar e observar a rodada", commands.run,
      "Altera o cenário escolhido. Guarde o run_id da saída e mantenha este terminal aberto. Não há recuperação automática ao finalizar ou interromper.",
      "Preencha operador, versão, SHA completo, repetição, limite e credencial administrativa. CPU admite observação até 1800 s.");
    $("runbook").replaceChildren();
    const steps = config.arm === "hitl" ? ["Espere o alerta real no Zabbix e identifique o host.",
      "Abra o Polaris e leia diagnóstico, evidências, confiança, script, alvo e efeitos.",
      "Aprove ou rejeite pela interface normal. A aprovação fica persistida antes da execução.",
      "Acompanhe o resultado e a medição independente; confira correção e efeitos colaterais."] : RUNBOOKS[config.scenario];
    for (const step of steps) {
      const item = document.createElement("li"); item.textContent = step; $("runbook").appendChild(item);
    }
    if (config.arm === "hitl") showCommand($("record-commands"), "Vincular incidente e evento", commands.link,
      "Use os IDs exatos, sem inferir o incidente mais recente. Uma falha válida sem incidente pode receber avaliação negativa.", "Preencha ID da rodada, ID do incidente e ID do evento.");
    showCommand($("record-commands"), "Persistir a avaliação", commands.assess,
      `Baixe o JSON e transfira para ${commands.assessmentPath} no servidor antes de executar. Não substitui uma avaliação já gravada.`, "Preencha ID da rodada e identificador válido da sessão.");
    showCommand($("close-commands"), "Descartar ensaio ou medição inválida", commands.discard,
      "Preserva timestamps e evidências. Não use descarte para esconder uma tentativa válida que falhou.", "Preencha ID da rodada e motivo real para gerar este comando opcional.");
    showCommand($("close-commands"), "Salvar backup do banco", commands.backup,
      "Grava no host, em arquivo novo. Se falhar, mantém .partial para inspeção; não é um backup completo.", "Preencha ID da rodada a encerrar e identificador válido da sessão.");
    showCommand($("close-commands"), "Exportar rodadas e relatório", commands.report,
      "Preserva todas as rodadas, incluindo descartadas. Ensaios devem estar descartados antes da análise. Sem gráficos; nenhum pacote adicional.", "Preencha ID da rodada a encerrar e identificador válido da sessão.");
    showCommand($("close-commands"), "Restaurar o cenário desta rodada", commands.reset,
      "Execute só após avaliação/descarte e backup. Não é a ação de remediação do braço manual. Depois, os três cenários são inspecionados.", "Preencha ID da rodada a encerrar e a credencial administrativa.");
  }

  async function refresh() {
    $("refresh").disabled = true;
    $("health").textContent = "Consultando o diagnóstico…";
    $("dependencies").replaceChildren();
    try {
      const response = await fetch("/api/v1/diagnostico");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      for (const check of data.verificacoes) {
        const item = document.createElement("li");
        item.textContent = `${check.nome}: ${check.estado}`;
        item.title = check.detalhe;
        $("dependencies").appendChild(item);
      }
      const history = data.configuracao.find((item) => item.chave === "POLARIS_CONFIDENCE_HISTORY");
      const debug = data.configuracao.find((item) => item.chave === "POLARIS_DEBUG");
      const alerts = [];
      if (String(history?.valor).toLowerCase() !== "false") alerts.push("Desligue POLARIS_CONFIDENCE_HISTORY antes das condições controladas.");
      if (String(debug?.valor).toLowerCase() !== "false") alerts.push("Confirme POLARIS_DEBUG=false.");
      $("health").textContent = `Consultado às ${new Date().toLocaleTimeString("pt-BR")}. ` + alerts.join(" ")
        + " O diagnóstico não substitui o checklist global nem a conferência humana.";
    } catch (error) {
      $("health").textContent = `Diagnóstico indisponível: ${error.message}. Execute a inspeção no servidor.`;
    } finally { $("refresh").disabled = false; }
  }

  document.querySelectorAll("#lab-tabs button").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll("#lab-tabs button").forEach((item) => item.removeAttribute("aria-current"));
    button.setAttribute("aria-current", "step");
    document.querySelectorAll("[data-panel]").forEach((panel) => panel.classList.toggle("oculto", panel.dataset.panel !== button.dataset.step));
  }));
  $("form").addEventListener("submit", (event) => event.preventDefault());
  for (const name of fields) $(name).addEventListener("input", () => {
    if (name === "run-id") $("close-id").value = $("run-id").value;
    render();
  });
  $("refresh").addEventListener("click", refresh);
  $("download-assessment").addEventListener("click", () => {
    try {
      const commands = draft(readConfig());
      if (!commands.assessmentPath) throw new Error("Preencha ID da rodada e identificador válido da sessão.");
      const record = assessment({steps: $("steps").value, commands: $("commands").value,
        resolved: $("resolved").value, observations: $("observations").value});
      const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2) + "\n"], {type: "application/json"}));
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = commands.assessmentPath.split("/").pop();
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      root.setTimeout(() => URL.revokeObjectURL(url), 1000);
      $("download-status").textContent = `JSON preparado. Confira o download e transfira para ${commands.assessmentPath} no servidor; ainda não foi gravado no banco.`;
    } catch (error) { $("download-status").textContent = error.message; }
  });
  render();
})(typeof globalThis !== "undefined" ? globalThis : this);
