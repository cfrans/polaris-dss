/* Interface Human-in-the-Loop.
   JavaScript puro, sem framework nem etapa de build. A atualização da lista é por sondagem a cada
   3 s; WebSocket seria complexidade sem retorno neste escopo. */

const INTERVALO_LISTA_MS = 3000;
const INTERVALO_RESULTADO_MS = 1000;
const OPERADOR = "operador";

const estado = {
  selecionado: null,
  exibicaoRegistrada: new Set(),
  confirmandoBandaBaixa: false,
  debug: false,
  catalogo: null,
  indiceScript: 0,
};

const $ = (id) => document.getElementById(id);

async function api(caminho, opcoes = {}) {
  const resposta = await fetch(caminho, {
    headers: { "Content-Type": "application/json" },
    ...opcoes,
  });
  const corpo = resposta.status === 204 ? null : await resposta.json();
  if (!resposta.ok) {
    throw new Error(corpo?.mensagem || corpo?.detail?.mensagem || `Falha na requisição (${resposta.status})`);
  }
  return corpo;
}

const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);

/* ---------- home ---------- */

let pendingTotal = null;
let pendingCheckedAt = null;
let recentRequest = 0;
let recentSignature = null;
let recentItems = [];
let recentAvailable = false;
const hiddenStorageKey = "polaris.hidden.incidents.v1";
const hiddenRecords = readHiddenRecords();
const unmatchedStorageKey = "polaris.show.unmatched.v1";
let includeUnmatched = readUnmatchedPreference();
$("show-unmatched").checked = includeUnmatched;

function readUnmatchedPreference() {
  try { return localStorage.getItem(unmatchedStorageKey) === "true"; }
  catch { return false; }
}

function setUnmatchedVisibility(show) {
  includeUnmatched = show;
  $("show-unmatched").checked = show;
  if (!show && $("recent-filter").value === "no_match") $("recent-filter").value = "";
  try { localStorage.setItem(unmatchedStorageKey, String(show)); }
  catch {
    $("hidden-feedback").textContent = "Preferência aplicada apenas nesta sessão; o navegador não permitiu salvá-la.";
    $("hidden-feedback").classList.remove("oculto");
  }
  recentSignature = null;
  return loadRecentIncidents();
}

function readHiddenRecords() {
  try {
    const stored = JSON.parse(localStorage.getItem(hiddenStorageKey) || "[]");
    return new Map(Array.isArray(stored) ? stored.filter(item => Number.isSafeInteger(item?.id) && item.id > 0)
      .map(item => [item.id, {id: item.id, nome_regra: String(item.nome_regra ?? "Incidente"),
        hostname: String(item.hostname ?? "—"), ts_criacao: item.ts_criacao}]) : []);
  } catch { return new Map(); }
}

function closeTools() {
  window.PolarisUI.setDisclosure($("tools-panel"), $("tools-toggle"), false);
}

function updateHomeQueue(total, checkedAt = new Date()) {
  pendingTotal = total;
  pendingCheckedAt = checkedAt;
  $("home-state").dataset.state = total == null ? "unknown" : total === 0 ? "ok" : "attention";
  document.querySelector(".painel").classList.toggle("queue-empty", total === 0 && estado.selecionado == null);
  $("home-pending").textContent = total == null ? "—" : total >= 50 ? "50+" : total;
  $("home-title").textContent = total == null ? "Não foi possível consultar a fila"
    : total === 0 ? "Nenhuma decisão pendente"
    : `${total >= 50 ? "50 ou mais" : total} incidente(s) aguardando sua análise`;
  $("home-description").textContent = total == null
    ? "Confira a conexão antes de considerar a fila vazia. O diagnóstico está no menu Ferramentas."
    : total === 0
      ? "Continue acompanhando os alertas no Zabbix. Quando houver uma sugestão para analisar, ela aparecerá aqui."
      : "Selecione um incidente na fila para conferir as evidências e a ação sugerida antes de decidir.";
  $("home-queue-time").textContent = total == null ? "Consulta indisponível"
    : `Consultada às ${checkedAt.toLocaleTimeString("pt-BR")}`;
  document.title = total > 0 ? `(${total >= 50 ? "50+" : total}) Polaris DSS` : "Polaris DSS — Suporte à Decisão";
}

function showHome(event) {
  if (event && (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button > 0)) return;
  event?.preventDefault();
  estado.selecionado = null;
  estado.confirmandoBandaBaixa = false;
  closeTools();
  $("tela-diagnostico").classList.add("oculto");
  $("detalhe").classList.add("oculto");
  $("placeholder").classList.remove("oculto");
  document.querySelector(".painel").classList.remove("oculto");
  document.querySelectorAll(".item.ativo").forEach(item => item.classList.remove("ativo"));
  updateHomeQueue(pendingTotal, pendingCheckedAt);
}

const incidentLabels = {
  pendente: "Aguardando decisão", executando: "Em execução", sucesso: "Sucesso",
  falha: "Falha", timeout: "Tempo esgotado", rejeitado: "Rejeitado",
  encerrado_na_origem: "Encerrado no Zabbix", no_match: "Sem regra compatível",
};

async function loadRecentIncidents() {
  const request = ++recentRequest;
  const filter = $("recent-filter").value;
  let data;
  try {
    data = await api(`/api/v1/incidentes?status=${encodeURIComponent(filter)}&limit=6&include_unmatched=${includeUnmatched}`);
  } catch {
    if (request !== recentRequest) return;
    recentSignature = null;
    recentAvailable = false;
    recentItems = [];
    $("recent-incidents").replaceChildren();
    $("recent-message").textContent = "Não foi possível consultar os registros. Nova tentativa em até 15 segundos.";
    $("recent-message").classList.remove("oculto");
    return;
  }
  if (request !== recentRequest) return;
  recentAvailable = true;
  const signature = JSON.stringify([filter, includeUnmatched, data.itens, [...hiddenRecords.keys()]]);
  if (signature === recentSignature) return;
  recentSignature = signature;
  recentItems = data.itens;
  renderRecentIncidents();
}

function renderRecentIncidents() {
  if (!recentAvailable) {
    $("recent-incidents").replaceChildren();
    $("recent-message").textContent = "Não foi possível consultar os registros. Nova tentativa em até 15 segundos.";
    $("recent-message").classList.remove("oculto");
    renderHiddenRecords();
    return;
  }
  const eligible = recentItems.filter(item => includeUnmatched || item.regra != null);
  const visible = eligible.filter(item => !hiddenRecords.has(item.id));
  $("recent-message").classList.toggle("oculto", visible.length > 0);
  $("recent-message").textContent = eligible.length > 0
    ? "Os registros deste filtro estão na área de ocultos." : includeUnmatched
      ? "Nenhum incidente neste filtro." : "Nenhum incidente com regra neste filtro. Você pode incluir os alertas sem regra abaixo.";
  const list = $("recent-incidents");
  list.replaceChildren();
  for (const item of visible) list.appendChild(createRecentRow(item));
  renderHiddenRecords();
}

function createRecentRow(item, hidden = false) {
    const row = document.createElement("li");
    row.className = `recent-row ${hidden ? "is-hidden" : `record-${item.status}`}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recent-item";
    for (const [className, text] of [
      ["recent-name", `#${item.id} · ${item.nome_regra ?? (item.regra
        ? `Regra ${item.regra} indisponível na base atual` : "Sem regra compatível")}`],
      ["recent-meta", `${item.hostname ?? "—"} · entrada ${formatarData(item.ts_criacao)}`],
      [`recent-status status-${hidden ? "hidden" : Object.hasOwn(incidentLabels, item.status) ? item.status : "unknown"}`,
        hidden ? "Oculto" : incidentLabels[item.status] ?? item.status],
    ]) {
      const field = document.createElement("span");
      field.className = className;
      field.textContent = text;
      button.appendChild(field);
    }
    button.addEventListener("click", () => abrir(item.id));
    row.appendChild(button);
    const visibility = document.createElement("button");
    visibility.type = "button";
    visibility.className = "icon-button visibility-button";
    const label = `${hidden ? "Exibir novamente" : "Ocultar dos recentes"} o incidente #${item.id}`;
    visibility.title = label;
    visibility.setAttribute("aria-label", label);
    visibility.appendChild(window.PolarisUI.icon(hidden ? "eye" : "eye-off"));
    visibility.addEventListener("click", () => setRecordHidden(item, !hidden));
    row.appendChild(visibility);
    return row;
}

function renderHiddenRecords() {
  $("hidden-count").textContent = hiddenRecords.size;
  const list = $("hidden-incidents");
  list.replaceChildren();
  for (const item of hiddenRecords.values()) list.appendChild(createRecentRow(item, true));
  if (!hiddenRecords.size) {
    const empty = document.createElement("li");
    empty.className = "hidden-empty";
    empty.textContent = "Nenhum registro oculto.";
    list.appendChild(empty);
  }
}

function setRecordHidden(item, hidden) {
  if (hidden) hiddenRecords.set(item.id, {id: item.id, nome_regra: item.nome_regra,
    hostname: item.hostname, ts_criacao: item.ts_criacao});
  else hiddenRecords.delete(item.id);
  let saved = true;
  try { localStorage.setItem(hiddenStorageKey, JSON.stringify([...hiddenRecords.values()])); }
  catch { saved = false; }
  recentSignature = null;
  renderRecentIncidents();
  $("hidden-feedback").textContent = saved
    ? `Incidente #${item.id} ${hidden ? "oculto dos recentes" : "deixou de ficar oculto"}.`
    : "Preferência aplicada apenas nesta sessão; o navegador não permitiu salvá-la.";
  $("hidden-feedback").classList.remove("oculto");
  $("hidden-records").querySelector("summary").focus();
}

/* ---------- ciência sobre a execução remota ---------- */

const CHAVE_CIENCIA = "polaris.ciencia.scripts";
const CHAVE_FAIXA = "polaris.faixa.oculta";
let descriptionAnimation = null;
let descriptionExpanded = false;

function resetScriptDescription() {
  if (descriptionAnimation) {
    descriptionAnimation.onfinish = null;
    descriptionAnimation.cancel();
    descriptionAnimation = null;
  }
  descriptionExpanded = false;
  const details = $("ciencia-descricao");
  details.open = false;
  details.style.overflow = "";
}

function toggleScriptDescription(event) {
  event.preventDefault();
  const details = $("ciencia-descricao");
  const summary = details.querySelector("summary");
  const startHeight = details.getBoundingClientRect().height;
  const opening = !descriptionExpanded;
  if (descriptionAnimation) {
    descriptionAnimation.onfinish = null;
    descriptionAnimation.cancel();
    descriptionAnimation = null;
  }
  descriptionExpanded = opening;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !details.animate) {
    details.open = opening;
    details.style.overflow = "";
    return;
  }
  details.open = true;
  const endHeight = opening ? details.getBoundingClientRect().height
    : summary.getBoundingClientRect().height;
  details.style.overflow = "hidden";
  const animation = details.animate(
    [{height: `${startHeight}px`}, {height: `${endHeight}px`}],
    {duration: 180, easing: "ease-in-out"},
  );
  descriptionAnimation = animation;
  animation.onfinish = () => {
    details.open = opening;
    details.style.overflow = "";
    descriptionAnimation = null;
  };
}

function lerPreferencia(chave) {
  try { return localStorage.getItem(chave); } catch { return null; }
}

function guardarPreferencia(chave, valor) {
  try { localStorage.setItem(chave, valor); } catch { /* Reaparece no próximo acesso. */ }
}

function atualizarFaixa() {
  const versao = estado.catalogo?.versao;
  const mostrar = versao && lerPreferencia(CHAVE_CIENCIA) === versao
    && lerPreferencia(CHAVE_FAIXA) !== versao;
  $("faixa-ciencia").classList.toggle("oculto", !mostrar);
}

function mostrarScript(indice) {
  if (!estado.catalogo?.scripts.length) return;
  const total = estado.catalogo.scripts.length;
  estado.indiceScript = (indice + total) % total;
  const script = estado.catalogo.scripts[estado.indiceScript];
  $("ciencia-script-nome").textContent = script.nome;
  $("ciencia-contador").textContent = `${estado.indiceScript + 1} de ${total}`;
  const description = window.PolarisScriptViewer.describeScript(script.nome);
  $("ciencia-script-titulo").textContent = description.title;
  $("ciencia-script-finalidade").textContent = description.purpose;
  $("ciencia-script-efeitos").textContent = description.effect;
  window.PolarisScriptViewer.renderScript($("ciencia-codigo"), script.conteudo,
    $("ciencia-colorir").checked);
}

async function carregarScripts(forcarExibicao = false) {
  $("tela-ciencia").classList.remove("oculto");
  resetScriptDescription();
  $("tela-ciencia").scrollTop = 0;
  $("btn-continuar-ciencia").disabled = true;
  try {
    estado.catalogo = await api("/api/v1/scripts-padrao");
    mostrarScript(0);
    $("ciencia-erro").classList.add("oculto");
    $("btn-recarregar-scripts").classList.add("oculto");
    $("btn-continuar-ciencia").disabled = false;
    if (!forcarExibicao && lerPreferencia(CHAVE_CIENCIA) === estado.catalogo.versao) {
      $("tela-ciencia").classList.add("oculto");
      atualizarFaixa();
    }
  } catch (erro) {
    $("ciencia-erro").textContent = `Não foi possível carregar os scripts: ${erro.message}`;
    $("ciencia-erro").classList.remove("oculto");
    $("btn-recarregar-scripts").classList.remove("oculto");
  }
}

function continuarAposCiencia() {
  if (!estado.catalogo) return;
  guardarPreferencia(CHAVE_CIENCIA, estado.catalogo.versao);
  $("tela-ciencia").classList.add("oculto");
  atualizarFaixa();
}

/* ---------- saúde ---------- */

async function atualizarSaude() {
  try {
    const s = await api("/health");
    $("system-version").textContent = s.versao ? `v${s.versao}` : "versão —";
    $("home-connection").textContent = s.db === "ok" ? "Conectados" : "Verificar banco";
    $("connection-stat").dataset.state = s.db === "ok" ? "ok" : "falha";
    window.PolarisUI.setConnection($("connection-db"), s.db === "ok" ? "ok" : "falha", new Date());
    $("estado-kb").textContent = `base v${s.versao_kb ?? "—"}`;
    $("estado-db").textContent = `banco ${s.db}`;
    $("estado-db").classList.toggle("ruim", s.db !== "ok");
    // O botão de simulação vem da flag de saúde. Sondar o endpoint de simulação criaria um
    // incidente a cada carregamento da página e contaminaria a trilha de auditoria.
    estado.debug = s.debug === true;
    $("btn-simular").classList.toggle("oculto", !estado.debug);
  } catch {
    $("system-version").textContent = "versão —";
    $("estado-kb").textContent = "base indisponível";
    $("home-connection").textContent = "Indisponíveis";
    $("connection-stat").dataset.state = "unknown";
    window.PolarisUI.setConnection($("connection-db"), "unknown");
    $("estado-db").textContent = "banco não verificado";
    $("estado-db").classList.add("ruim");
  }
}

let checkingConnections = false;
let connectionsCheckedAt = 0;
async function refreshConnections() {
  if (checkingConnections) return;
  checkingConnections = true;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const data = await api("/api/v1/conectividade", {signal: controller.signal});
    for (const check of data.verificacoes) {
      const indicator = check.id === "banco" ? $("connection-db")
        : check.id === "zabbix" ? $("connection-zabbix") : null;
      if (indicator) window.PolarisUI.setConnection(indicator, check.estado, data.verificado_em, check.latencia_ms);
    }
  } catch {
    window.PolarisUI.setConnection($("connection-zabbix"), "unknown");
  } finally {
    clearTimeout(timer);
    connectionsCheckedAt = Date.now();
    checkingConnections = false;
  }
}

/* ---------- reconciliação ---------- */

const ROTULO_RECONCILIACAO = {
  sucesso: "operacional",
  erro: "falha no último ciclo",
  atrasada: "sem ciclo recente",
  aguardando_primeiro_ciclo: "aguardando primeiro ciclo",
  desativada: "desativada",
};

const formatarData = (valor) => valor
  ? new Date(valor).toLocaleString("pt-BR")
  : "—";

function resumoCiclo(ciclo) {
  if (!ciclo) return "nenhum ciclo registrado";
  const counts = `${ciclo.recuperados} recuperado(s), ${ciclo.ja_conhecidos} conhecido(s), `
    + `${ciclo.encerrados_na_origem} encerrado(s) na origem`;
  return ciclo.status === "erro" ? `${ciclo.mensagem_erro || "erro sem detalhe"}\n${counts}` : counts;
}

async function obterReconciliacao() {
  return api("/api/v1/reconciliacao");
}

async function atualizarReconciliacao() {
  const badge = $("estado-reconciliacao");
  try {
    const dados = await obterReconciliacao();
    $("reconciliation-label").textContent = `Reconciliação ${ROTULO_RECONCILIACAO[dados.status] ?? dados.status}`;
    badge.dataset.state = dados.status === "sucesso" ? "ok" : dados.status === "erro" ? "falha" : "attention";
    badge.title = `Reconciliação: ${ROTULO_RECONCILIACAO[dados.status] ?? dados.status}`;
    badge.classList.toggle("ruim", dados.status === "erro" || dados.status === "atrasada");
    badge.classList.toggle("atencao", dados.status === "aguardando_primeiro_ciclo");
    $("home-running").textContent = dados.contagens_incidentes.executando ?? 0;
    $("home-last-cycle").textContent = formatarData(dados.ultimo_ciclo?.ts_conclusao);
    $("home-reconciliation").textContent = ROTULO_RECONCILIACAO[dados.status] ?? dados.status;
    $("reconciliation-stat").dataset.state = badge.dataset.state;
  } catch {
    $("reconciliation-label").textContent = "Reconciliação indisponível";
    badge.dataset.state = "unknown";
    badge.classList.add("ruim");
    badge.classList.remove("atencao");
    $("home-running").textContent = "—";
    $("home-last-cycle").textContent = "—";
    $("home-reconciliation").textContent = "Consulta indisponível";
    $("reconciliation-stat").dataset.state = "unknown";
  }
}

async function abrirReconciliacao() {
  const open = $("estado-reconciliacao").getAttribute("aria-expanded") !== "true";
  window.PolarisUI.setDisclosure($("reconciliation-shell"), $("estado-reconciliacao"), open);
  if (open) await carregarReconciliacao();
}

function fecharReconciliacao() {
  window.PolarisUI.setDisclosure($("reconciliation-shell"), $("estado-reconciliacao"), false);
  $("estado-reconciliacao").focus();
}

async function carregarReconciliacao() {
  const refreshButton = $("btn-refresh-reconciliation");
  refreshButton.disabled = true;
  let dados;
  try {
    dados = await obterReconciliacao();
  } catch (erro) {
    const aviso = $("recon-aviso");
    aviso.textContent = `Não foi possível consultar a reconciliação: ${erro.message}`;
    aviso.classList.remove("oculto");
    for (const id of ["recon-status", "recon-ultima", "recon-intervalo", "recon-resultado", "recon-history-count"]) {
      $(id).textContent = "—";
    }
    $("recon-contagens").replaceChildren();
    $("recon-historico").replaceChildren();
    return;
  } finally {
    refreshButton.disabled = false;
  }

  $("recon-aviso").classList.add("oculto");
  $("recon-status").textContent = ROTULO_RECONCILIACAO[dados.status] ?? dados.status;
  $("recon-ultima").textContent = formatarData(dados.ultimo_ciclo?.ts_conclusao);
  $("recon-intervalo").textContent = dados.habilitada
    ? `${dados.intervalo_segundos} s`
    : "desativado";
  $("recon-resultado").textContent = resumoCiclo(dados.ultimo_ciclo);

  const contagens = $("recon-contagens");
  contagens.innerHTML = "";
  const ordem = ["pendente", "executando", "sucesso", "falha", "timeout", "rejeitado",
    "encerrado_na_origem", "no_match"];
  for (const status of ordem) {
    const total = dados.contagens_incidentes[status] ?? 0;
    const li = document.createElement("li");
    li.textContent = status.replaceAll("_", " ");
    const valor = document.createElement("strong");
    valor.textContent = total;
    li.appendChild(valor);
    contagens.appendChild(li);
  }

  const historico = $("recon-historico");
  historico.replaceChildren();
  $("recon-history-count").textContent = dados.historico.length;
  if (!dados.historico.length) {
    const emptyMessage = document.createElement("li");
    emptyMessage.className = "recon-empty";
    emptyMessage.textContent = "Nenhuma atividade significativa registrada.";
    historico.appendChild(emptyMessage);
    return;
  }
  for (const ciclo of dados.historico) {
    const row = document.createElement("li");
    row.className = "recon-line";
    for (const [className, value] of [
      ["recon-time", formatarData(ciclo.ts_conclusao)],
      [ciclo.status === "erro" ? "recon-error" : "recon-ok", ciclo.status === "erro" ? "ERRO" : "OK"],
      ["recon-message", resumoCiclo(ciclo)],
    ]) {
      const field = document.createElement("span");
      field.className = className;
      field.textContent = value;
      row.appendChild(field);
    }
    historico.appendChild(row);
  }
}

/* ---------- lista ---------- */

async function carregarLista() {
  let dados;
  try {
    dados = await api("/api/v1/incidentes?status=pendente&limit=50");
  } catch {
    updateHomeQueue(null);
    $("contador").textContent = "—";
    $("lista").replaceChildren();
    $("lista-vazia").textContent = "Fila indisponível. Tentando novamente…";
    $("lista-vazia").classList.remove("oculto");
    return;
  }

  updateHomeQueue(dados.total);
  $("contador").textContent = dados.total >= 50 ? "50+" : dados.total;
  $("lista-vazia").textContent = "Nenhum incidente aguardando decisão.";
  $("lista-vazia").classList.toggle("oculto", dados.total > 0);

  const lista = $("lista");
  lista.innerHTML = "";

  for (const item of dados.itens) {
    const li = document.createElement("li");
    li.className = `item ${item.banda ?? ""}`;
    if (item.id === estado.selecionado) li.classList.add("ativo");
    li.innerHTML = `
      <div class="item-topo">
        <span class="item-regra">${item.regra ?? "sem regra"}</span>
        <span class="item-conf cor-${item.banda ?? ""}">${pct(item.confianca)}</span>
      </div>
      <div class="item-nome">${item.nome_regra ?? "Incidente sem heurística formalizada"}</div>
      <div class="item-meta">${item.hostname ?? "—"} · ${new Date(item.ts_criacao).toLocaleTimeString("pt-BR")}</div>
    `;
    li.addEventListener("click", () => abrir(item.id));
    lista.appendChild(li);
  }
}

/* ---------- detalhe ---------- */

async function abrir(id) {
  const previousSelection = estado.selecionado;
  estado.selecionado = id;
  estado.confirmandoBandaBaixa = false;

  let inc;
  try {
    inc = await api(`/api/v1/incidentes/${id}`);
  } catch (error) {
    if (estado.selecionado !== id) return;
    estado.selecionado = previousSelection;
    alert(`Não foi possível abrir o incidente: ${error.message}`);
    return;
  }
  if (estado.selecionado !== id) return;
  document.querySelector(".painel").classList.remove("queue-empty");

  $("placeholder").classList.add("oculto");
  $("detalhe").classList.remove("oculto");

  $("d-regra").textContent = inc.regra ?? "—";
  $("d-nome").textContent = inc.nome_regra ?? "Incidente sem heurística formalizada";
  $("d-host").textContent = `${inc.hostname ?? "—"} · evento ${inc.id_evento ?? "—"} · severidade ${inc.severidade ?? "—"}`;

  $("d-confianca").textContent = pct(inc.confianca);
  $("d-confianca").className = `confianca-valor cor-${inc.banda ?? ""}`;
  $("d-banda").textContent = inc.banda ?? "—";
  $("d-banda").className = `confianca-banda banda-${inc.banda ?? ""}`;
  $("d-base").textContent = `teto da regra: ${pct(inc.confianca_base ?? (
    inc.fatores.length ? inc.confianca / produtoFatores(inc.fatores) : null
  ))}`;

  $("d-diagnostico").textContent = inc.diagnostico ?? "—";
  renderEvidencias(inc.evidencias);
  renderFatores(inc.fatores);
  renderDescartadas(inc.candidatas_descartadas);

  $("d-comando").textContent = inc.comando ?? "—";
  $("d-rollback").textContent = inc.rollback ?? "—";
  $("d-timeout").textContent = inc.timeout_segundos
    ? `${inc.timeout_segundos}s${inc.destrutiva ? " · ação destrutiva" : ""}`
    : "—";
  $("d-versoes").textContent = `base de conhecimento v${inc.versao_kb ?? "—"} · motor v${inc.versao_motor ?? "—"} · incidente #${inc.id}`;

  configurarAviso(inc);
  configurarDecisao(inc);
  renderActionPlan(inc);
  if (inc.plano?.estado === "coletando") {
    setTimeout(() => { if (estado.selecionado === inc.id) abrir(inc.id); }, 1000);
  }
  await registrarExibicao(inc);
  carregarLista();
}

function produtoFatores(fatores) {
  return fatores.reduce((acc, f) => acc * f.valor, 1);
}

function renderEvidencias(ev) {
  const ul = $("d-evidencias");
  ul.innerHTML = "";
  if (!ev) return;

  const linhas = [];
  if (ev.metrica?.aplicavel) {
    linhas.push([
      ev.metrica.cruzou ? "confirma" : "não confirma",
      ev.metrica.cruzou ? "ev-sim" : "ev-nao",
      `${ev.metrica.chave ?? "métrica"}: <strong>${ev.metrica.valor}</strong> ${ev.metrica.operador} ${ev.metrica.limiar}`,
    ]);
  } else {
    linhas.push(["não aplicável", "ev-na", "a regra não avalia métrica numérica para este alerta"]);
  }

  if (ev.texto?.aplicavel) {
    linhas.push([
      ev.texto.casou ? "confirma" : "não confirma",
      ev.texto.casou ? "ev-sim" : "ev-nao",
      ev.texto.casou
        ? `padrão encontrado no texto do alerta: <em>“${escapar(ev.texto.trecho ?? "")}”</em>`
        : "o padrão textual da regra não foi encontrado no alerta",
    ]);
  } else {
    linhas.push(["não aplicável", "ev-na", "a regra não declara condição textual"]);
  }

  for (const [rotulo, classe, texto] of linhas) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="marca-ev ${classe}">${rotulo}</span><span>${texto}</span>`;
    ul.appendChild(li);
  }
}

function renderFatores(fatores) {
  const ul = $("d-fatores");
  ul.innerHTML = "";
  for (const f of fatores) {
    const neutro = f.valor >= 1;
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="fator-peso ${neutro ? "fator-neutro" : "fator-desconto"}">
        ${neutro ? "&times;1,00" : `&times;${f.valor.toFixed(2).replace(".", ",")}`}
      </span>
      <span>${escapar(f.motivo)}</span>
    `;
    ul.appendChild(li);
  }
}

function renderDescartadas(lista) {
  const bloco = $("bloco-descartadas");
  const ul = $("d-descartadas");
  ul.innerHTML = "";
  bloco.classList.toggle("oculto", !lista?.length);
  for (const c of lista ?? []) {
    const li = document.createElement("li");
    li.textContent = `${c.regra} — ${c.nome_regra} (${pct(c.confianca)})`;
    ul.appendChild(li);
  }
}

function renderActionPlan(inc) {
  const plan = inc.plano;
  estado.planoAtual = plan ?? null;
  $("plano-acao").classList.toggle("oculto", !plan);
  if (!plan) return;
  $("plano-aviso").textContent = plan.aviso;
  $("plano-fonte").textContent = `Inspeção de leitura em ${new Date(plan.coletado_em).toLocaleString("pt-BR")}. O alvo será conferido novamente antes da ação.`;
  renderPlanEvidence($("plano-evidencias"), plan.evidencias);
  const select = $("plano-opcao");
  select.replaceChildren();
  for (const action of plan.opcoes) {
    const option = document.createElement("option");
    option.value = action.id;
    option.textContent = `${action.titulo} — ${pct(action.confianca)}${action.alvo.caminho ? ` — ${action.alvo.caminho}` : ""}`;
    select.appendChild(option);
  }
  if (inc.acao_escolhida) select.value = inc.acao_escolhida.id;
  select.disabled = inc.status !== "pendente" || !plan.opcoes.length;
  const update = () => {
    const action = plan.opcoes.find(a => a.id === select.value);
    if (!action) { $("btn-aprovar").disabled = true; return; }
    estado.confirmandoBandaBaixa = false;
    $("plano-motivo").textContent = `${action.motivo} Confiança técnica: ${pct(action.confianca_tecnica)}; preferência: ×${action.preferencia.fator.toFixed(2)} (${action.preferencia.escolhas} escolha(s)).`;
    const target = action.alvo;
    $("plano-alvo").textContent = target.caminho
      ? `${target.caminho} · ${target.bytes.toLocaleString("pt-BR")} bytes · proprietário ${target.proprietario} · modificado em ${new Date(target.mtime_ns / 1000000).toLocaleString("pt-BR")}`
      : target.pid ? `PID ${target.pid} · ${target.nome}` : `Serviço ${target.servico} · estado ${target.estado}`;
    $("d-comando").textContent = action.comando;
    $("d-rollback").textContent = action.rollback;
    $("d-confianca").textContent = pct(action.confianca);
    $("d-confianca").className = `confianca-valor cor-${action.banda}`;
    $("d-banda").textContent = action.banda;
    $("d-banda").className = `confianca-banda banda-${action.banda}`;
    $("d-timeout").textContent = `${action.timeout_segundos}s${action.destrutiva ? " · exige confirmação adicional" : ""}`;
    if (inc.fatores && action.historico_acao) {
      const history = action.historico_acao;
      const factors = inc.fatores.filter(f => f.id !== "F3");
      factors.push({id: "F3_acao", valor: history.fator,
        motivo: history.habilitado
          ? `Histórico desta operação: ${history.sucessos}/${history.n} sucesso(s); desconto conforme os limiares de F3.`
          : "Histórico desta operação desativado; fator neutro."});
      factors.push({id: "P", valor: action.preferencia.fator,
        motivo: `Preferência: ${action.preferencia.modo}; ${action.preferencia.escolhas} escolha(s). ${action.preferencia.aplicada ? "Aplicada após amostra mínima." : "Sem desconto de preferência."}`});
      renderFatores(factors);
    }
    configurarDecisao({...inc, banda: action.banda, destrutiva: action.destrutiva});
  };
  select.onchange = update;
  update();
  $("btn-atualizar-plano").disabled = inc.status !== "pendente";
  if (plan.estado === "coletando") $("btn-atualizar-plano").disabled = true;
  $("btn-atualizar-plano").onclick = async () => {
    $("btn-atualizar-plano").disabled = true;
    try {
      await api(`/api/v1/incidentes/${inc.id}/diagnostico`, {method: "POST"});
      await abrir(inc.id);
    } catch (error) {
      alert(error.message);
      $("btn-atualizar-plano").disabled = false;
    }
  };
}

function renderPlanEvidence(container, evidence) {
  container.replaceChildren();
  const line = text => {
    const p = document.createElement("p");
    p.textContent = text;
    container.appendChild(p);
  };
  if (evidence.erro) line(evidence.erro);
  if (evidence.arquivos) {
    line(`Volume /mnt/polaris_test · espaço livre: ${(evidence.espaco_livre ?? 0).toLocaleString("pt-BR")} bytes.`);
    for (const file of evidence.arquivos) {
      line(`${file.caminho} · ${file.bytes.toLocaleString("pt-BR")} bytes · ${file.proprietario} · ${new Date(file.mtime_ns / 1000000).toLocaleString("pt-BR")} · ${file.aberto === false ? "sem descritor aberto observado" : file.aberto ? "em uso" : "uso não confirmado"}`);
    }
    if (!evidence.completo) line("Inspeção limitada ou incompleta; ausência na lista não comprova ausência no volume.");
  }
  if (evidence.estado_servico) line(`nginx: ${evidence.estado_servico}.`);
  for (const finding of evidence.indicios ?? []) {
    line(`Indício de ${finding.codigo}: “${finding.trecho}” · fonte ${finding.fonte}.`);
  }
  if (evidence.estado_servico && !evidence.indicios?.length) line("Nenhum dos padrões conhecidos foi encontrado; isso não descarta outras causas.");
  if (evidence.processo) line(`Maior consumo na amostra: PID ${evidence.processo.pid} · ${evidence.processo.nome}.`);
  if (evidence.limite) line(evidence.limite);
  if (evidence.fonte) line(evidence.fonte);
}

function configurarAviso(inc) {
  const aviso = $("aviso-banda");
  const recorrencia = inc.fatores.find((f) => f.id === "F4" && f.valor < 1);

  if (recorrencia) {
    aviso.innerHTML = `<strong>Incidente recorrente.</strong> ${escapar(recorrencia.motivo)}.
      Reaplicar a mesma remediação provavelmente não resolve — recomenda-se investigação manual
      antes de aprovar.`;
    aviso.classList.remove("oculto");
  } else if (inc.banda === "baixa") {
    aviso.innerHTML = `<strong>Confiança baixa.</strong> A evidência disponível não sustenta o
      diagnóstico com segurança. Verifique o contexto antes de aprovar.`;
    aviso.classList.remove("oculto");
  } else {
    aviso.classList.add("oculto");
  }
}

function configurarDecisao(inc) {
  const pendente = inc.status === "pendente";
  $("decisao").classList.toggle("oculto", !pendente);
  $("confirmacao").classList.add("oculto");

  const aprovar = $("btn-aprovar");
  const rejeitar = $("btn-rejeitar");
  aprovar.disabled = false;
  rejeitar.disabled = false;

  // Banda baixa não oferece aprovação em um clique: exige confirmação adicional. É a única
  // diferença de comportamento entre as bandas — nenhuma delas executa sozinha.
  const exigeConfirmacao = inc.banda === "baixa" || inc.destrutiva;
  aprovar.classList.toggle("atencao", exigeConfirmacao);
  aprovar.textContent = exigeConfirmacao ? "Aprovar mesmo assim" : "Aprovar e executar";

  aprovar.onclick = () => {
    if (exigeConfirmacao && !estado.confirmandoBandaBaixa) {
      estado.confirmandoBandaBaixa = true;
      $("confirmacao").textContent =
        "Ação destrutiva ou confiança baixa. Confira o alvo e clique novamente para confirmar.";
      $("confirmacao").classList.remove("oculto");
      return;
    }
    decidir(inc.id, true);
  };
  rejeitar.onclick = () => decidir(inc.id, false);

  if (inc.status !== "pendente") mostrarResultado(inc.id);
  else $("resultado").classList.add("oculto");
}

async function registrarExibicao(inc) {
  // Marca t3, o instante em que o operador efetivamente viu o incidente. Sem ele não existe tempo
  // de decisão humana, e o MTTR não pode ser decomposto.
  if (inc.status !== "pendente" || inc.plano?.estado === "coletando" || estado.exibicaoRegistrada.has(inc.id)) return;
  estado.exibicaoRegistrada.add(inc.id);
  try {
    await api(`/api/v1/incidentes/${inc.id}/exibicao`, { method: "PATCH" });
  } catch {
    estado.exibicaoRegistrada.delete(inc.id);
  }
}

/* ---------- decisão ---------- */

async function decidir(id, aprovado) {
  $("btn-aprovar").disabled = true;
  $("btn-rejeitar").disabled = true;
  $("confirmacao").classList.add("oculto");

  let motivo = null;
  if (!aprovado) {
    motivo = prompt("Motivo da rejeição (opcional):") || null;
  }

  try {
    await api(`/api/v1/incidentes/${id}/decisao`, {
      method: "POST",
      body: JSON.stringify({ aprovado, operador: OPERADOR, motivo,
        opcao_id: aprovado && estado.planoAtual ? $("plano-opcao").value : null,
        versao_plano: aprovado ? estado.planoAtual?.versao ?? null : null,
        versao_scripts: aprovado ? estado.catalogo?.versao : null }),
    });
  } catch (erro) {
    alert(erro.message);
    if (aprovado && erro.message.includes("scripts padrão mudaram")) {
      await carregarScripts(true);
    }
    $("btn-aprovar").disabled = false;
    $("btn-rejeitar").disabled = false;
    return;
  }

  $("decisao").classList.add("oculto");
  await mostrarResultado(id);
  await carregarLista();
}

async function mostrarResultado(id) {
  const bloco = $("resultado");
  const corpo = $("resultado-corpo");
  bloco.classList.remove("oculto");
  corpo.innerHTML = `<p class="resultado-status">executando…</p>`;

  for (let tentativa = 0; tentativa < 30; tentativa += 1) {
    const r = await api(`/api/v1/incidentes/${id}/resultado`);
    if (estado.selecionado !== id) return;
    if (r.status !== "executando") {
      const cor = r.status === "sucesso" ? "cor-alta" : r.status === "rejeitado" ? "" : "cor-baixa";
      corpo.innerHTML = `
        <p class="resultado-status ${cor}">${r.status}</p>
        ${r.output ? `<pre>${escapar(r.output)}</pre>` : ""}
        ${r.erro ? `<pre>${escapar(r.erro)}</pre>` : ""}
        <p class="resultado-meta">
          ${r.exit_code != null ? `código de saída ${r.exit_code} · ` : ""}
          ${r.mttr_segundos != null ? `tempo total ${r.mttr_segundos.toFixed(1)}s` : "sem conclusão registrada"}
        </p>`;
      return;
    }
    await new Promise((r) => setTimeout(r, INTERVALO_RESULTADO_MS));
  }
  if (estado.selecionado === id) corpo.innerHTML = `<p class="resultado-status cor-media">ainda em execução</p>`;
}

/* ---------- simulação ---------- */

const CENARIOS = [
  { tipo_alerta: "service_down", hostname: "vm-alvo-01", severidade: "critica",
    metrica: "proc.num[nginx]", valor: 0,
    texto: "nginx: service nginx is not running on vm-alvo-01. Active: inactive (dead)" },
  { tipo_alerta: "disk_full", hostname: "vm-alvo-01", severidade: "alta",
    metrica: "vfs.fs.size[/mnt/polaris_test,pused]", valor: 97.4,
    texto: "Filesystem /mnt/polaris_test: No space left on device" },
  { tipo_alerta: "cpu_high", hostname: "vm-alvo-01", severidade: "media",
    metrica: "system.cpu.util", valor: 92.1,
    texto: "High CPU utilization on vm-alvo-01" },
];

let proximoCenario = 0;

async function simular() {
  const cenario = CENARIOS[proximoCenario % CENARIOS.length];
  proximoCenario += 1;
  try {
    const r = await api("/debug/simulate-alert", {
      method: "POST",
      body: JSON.stringify(cenario),
    });
    await carregarLista();
    if (r.incidente_id) abrir(r.incidente_id);
  } catch (erro) {
    alert(erro.message);
  }
}

/* ---------- utilidades ---------- */

function escapar(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}


/* ---------- diagnóstico ---------- */

const ROTULO_ESTADO = {
  ok: "ok",
  aviso: "atenção",
  falha: "falha",
  nao_configurado: "não configurado",
};

function abrirDiagnostico() {
  document.querySelector(".painel").classList.add("oculto");
  $("tela-diagnostico").classList.remove("oculto");
  carregarDiagnostico();
}

function fecharDiagnostico() {
  $("tela-diagnostico").classList.add("oculto");
  document.querySelector(".painel").classList.remove("oculto");
}

async function carregarDiagnostico() {
  const lista = $("diag-verificacoes");
  lista.innerHTML = `<li class="diag-item"><span class="diag-estado">…</span>
    <span><span class="diag-nome">verificando dependências</span></span><span></span></li>`;

  let dados;
  try {
    dados = await api("/api/v1/diagnostico");
  } catch (erro) {
    lista.innerHTML = "";
    mostrarAvisoDiag(`Não foi possível executar o diagnóstico: ${escapar(erro.message)}`);
    return;
  }

  lista.innerHTML = "";
  for (const v of dados.verificacoes) {
    const li = document.createElement("li");
    li.className = `diag-item est-${v.estado}`;
    li.innerHTML = `
      <span class="diag-estado">${ROTULO_ESTADO[v.estado] ?? v.estado}</span>
      <span>
        <span class="diag-nome">${escapar(v.nome)}</span>
        <span class="diag-detalhe">${escapar(v.detalhe)}</span>
      </span>
      <span class="diag-latencia">${v.latencia_ms == null ? "" : v.latencia_ms + " ms"}</span>
    `;
    lista.appendChild(li);
  }

  const corpo = $("diag-config");
  corpo.innerHTML = "";
  for (const c of dados.configuracao) {
    const tr = document.createElement("tr");
    const classe = !c.definido ? "vazio-valor" : c.sensivel ? "mascarado" : "";
    tr.innerHTML = `<td>${escapar(c.chave)}</td><td class="${classe}">${escapar(c.valor)}</td>`;
    corpo.appendChild(tr);
  }

  const { falha = 0, aviso = 0 } = dados.resumo;
  if (falha) {
    mostrarAvisoDiag(`<strong>${falha} verificação(ões) falhando.</strong> O sistema não alcança
      alguma dependência — os itens marcados acima explicam o quê e sugerem o que fazer.`);
  } else if (aviso) {
    mostrarAvisoDiag(`<strong>${aviso} ponto(s) de atenção.</strong> Nada impede o funcionamento,
      mas há configuração incompleta.`);
  } else {
    $("diag-aviso").classList.add("oculto");
  }
}

function mostrarAvisoDiag(html) {
  const aviso = $("diag-aviso");
  aviso.innerHTML = html;
  aviso.classList.remove("oculto");
}

async function recarregarBase() {
  const botao = $("btn-recarregar-base");
  botao.disabled = true;
  try {
    const r = await api("/api/v1/regras/reload", { method: "POST" });
    mostrarAvisoDiag(`Base de regras recarregada: v${r.versao_kb}, ${r.regras} regra(s).`);
    await atualizarSaude();
    await carregarDiagnostico();
  } catch (erro) {
    // Base inválida mantém a anterior ativa: o erro informa sem derrubar o sistema.
    mostrarAvisoDiag(`<strong>Base de regras inválida.</strong> ${escapar(erro.message)}
      A base anterior continua em vigor.`);
  } finally {
    botao.disabled = false;
  }
}

/* ---------- início ---------- */


$("btn-simular").addEventListener("click", simular);
$("brand-home").addEventListener("click", showHome);
$("recent-filter").addEventListener("change", () => {
  if ($("recent-filter").value === "no_match" && !includeUnmatched) {
    setUnmatchedVisibility(true);
    return;
  }
  recentSignature = null;
  $("recent-incidents").replaceChildren();
  $("recent-message").textContent = "Consultando registros…";
  $("recent-message").classList.remove("oculto");
  loadRecentIncidents();
});
$("show-unmatched").addEventListener("change", () => setUnmatchedVisibility($("show-unmatched").checked));
$("tools-toggle").addEventListener("click", () => window.PolarisUI.setDisclosure($("tools-panel"),
  $("tools-toggle"), $("tools-toggle").getAttribute("aria-expanded") !== "true"));
document.querySelectorAll(".tools-links button, .tools-links a").forEach(item => item.addEventListener("click", closeTools));
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  if ($("tools-toggle").getAttribute("aria-expanded") === "true") {
    closeTools();
    $("tools-toggle").focus();
  } else if ($("estado-reconciliacao").getAttribute("aria-expanded") === "true") fecharReconciliacao();
});
document.addEventListener("click", event => {
  if (!$("tools-menu").contains(event.target)) closeTools();
});
$("connection-zabbix").addEventListener("click", abrirDiagnostico);
$("connection-db").addEventListener("click", abrirDiagnostico);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && Date.now() - connectionsCheckedAt >= 60000) refreshConnections();
});
$("estado-reconciliacao").addEventListener("click", abrirReconciliacao);
$("btn-fechar-reconciliacao").addEventListener("click", fecharReconciliacao);
$("btn-refresh-reconciliation").addEventListener("click", carregarReconciliacao);
$("btn-diagnostico").addEventListener("click", abrirDiagnostico);
$("btn-preferencias").addEventListener("click", async () => {
  closeTools();
  try {
    const preferences = await api("/api/v1/preferencias");
    $("pref-modo").value = preferences.modo_preferencia;
    $("pref-desconto").value = Math.round(preferences.desconto_maximo * 100);
    $("pref-minimo").value = preferences.minimo_escolhas;
    $("pref-historico").textContent = preferences.historico_habilitado
      ? "Histórico habilitado. Alterar preferências exige atualizar diagnósticos pendentes."
      : "Histórico desativado neste servidor. As preferências serão salvas, mas não afetarão as recomendações.";
    $("pref-feedback").textContent = "";
    $("preferencias-dialog").showModal();
  } catch (error) { alert(error.message); }
});
$("pref-fechar").addEventListener("click", () => $("preferencias-dialog").close());
$("preferencias-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("/api/v1/preferencias", {method: "PUT", body: JSON.stringify({
      modo_preferencia: $("pref-modo").value,
      desconto_maximo: Number($("pref-desconto").value) / 100,
      minimo_escolhas: Number($("pref-minimo").value),
    })});
    $("pref-feedback").textContent = "Preferências salvas. Atualize o diagnóstico antes da próxima aprovação.";
  } catch (error) { $("pref-feedback").textContent = error.message; }
});
$("btn-fechar-diagnostico").addEventListener("click", fecharDiagnostico);
$("btn-reverificar").addEventListener("click", carregarDiagnostico);
$("btn-recarregar-base").addEventListener("click", recarregarBase);
$("btn-scripts").addEventListener("click", () => carregarScripts(true));
$("ciencia-descricao").querySelector("summary").addEventListener("click", toggleScriptDescription);
$("ciencia-colorir").addEventListener("change", () => mostrarScript(estado.indiceScript));
$("btn-script-anterior").addEventListener("click", () => mostrarScript(estado.indiceScript - 1));
$("btn-script-proximo").addEventListener("click", () => mostrarScript(estado.indiceScript + 1));
$("btn-continuar-ciencia").addEventListener("click", continuarAposCiencia);
$("btn-recarregar-scripts").addEventListener("click", () => carregarScripts(true));
$("btn-ocultar-faixa").addEventListener("click", () => {
  guardarPreferencia(CHAVE_FAIXA, estado.catalogo.versao);
  atualizarFaixa();
});

carregarScripts();
atualizarSaude();
atualizarReconciliacao();
carregarLista();
loadRecentIncidents();
renderHiddenRecords();
refreshConnections();
setInterval(carregarLista, INTERVALO_LISTA_MS);
setInterval(atualizarSaude, 15000);
setInterval(atualizarReconciliacao, 15000);
setInterval(loadRecentIncidents, 15000);
setInterval(refreshConnections, 60000);
