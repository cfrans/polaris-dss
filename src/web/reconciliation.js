(function(root) {
  'use strict';
  function create({document,ui,api,onState=()=>{}}) {
    const $=id=>document.getElementById(id);

const labels = {
  sucesso: "operacional",
  erro: "falha no último ciclo",
  atrasada: "sem ciclo recente",
  aguardando_primeiro_ciclo: "aguardando primeiro ciclo",
  desativada: "desativada",
};

const formatDate = (valor) => valor
  ? (ui.formatDate?ui.formatDate(valor):new Date(valor).toLocaleString("pt-BR"))
  : "—";

function cycleSummary(ciclo) {
  if (!ciclo) return "nenhum ciclo registrado";
  const counts = `${ciclo.recuperados} recuperado(s), ${ciclo.ja_conhecidos} conhecido(s), `
    + `${ciclo.encerrados_na_origem} encerrado(s) na origem`;
  return ciclo.status === "erro" ? `${ciclo.mensagem_erro || "erro sem detalhe"}\n${counts}` : counts;
}

async function readState() {
  return api("/api/v1/reconciliacao");
}

async function refreshBadge() {
  const badge = $("estado-reconciliacao");
  try {
    const dados = await readState();
    $("reconciliation-label").textContent = `Reconciliação ${labels[dados.status] ?? dados.status}`;
    badge.dataset.state = dados.status === "sucesso" ? "ok" : dados.status === "erro" ? "falha" : "attention";
    badge.title = `Reconciliação: ${labels[dados.status] ?? dados.status}`;
    badge.classList.toggle("ruim", dados.status === "erro" || dados.status === "atrasada");
    badge.classList.toggle("atencao", dados.status === "aguardando_primeiro_ciclo");
    onState(dados, badge.dataset.state);
  } catch {
    $("reconciliation-label").textContent = "Reconciliação indisponível";
    badge.dataset.state = "unknown";
    badge.classList.add("ruim");
    badge.classList.remove("atencao");
    onState(null, "unknown");
  }
}

async function toggle() {
  const open = $("estado-reconciliacao").getAttribute("aria-expanded") !== "true";
  ui.setDisclosure($("reconciliation-shell"), $("estado-reconciliacao"), open);
  if (open) await load();
}

function close() {
  ui.setDisclosure($("reconciliation-shell"), $("estado-reconciliacao"), false);
  $("estado-reconciliacao").focus();
}

async function load() {
  const refreshButton = $("btn-refresh-reconciliation");
  refreshButton.disabled = true;
  let dados;
  try {
    dados = await readState();
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
  $("recon-status").textContent = labels[dados.status] ?? dados.status;
  $("recon-ultima").textContent = formatDate(dados.ultimo_ciclo?.ts_conclusao);
  $("recon-intervalo").textContent = dados.habilitada
    ? `${dados.intervalo_segundos} s`
    : "desativado";
  $("recon-resultado").textContent = cycleSummary(dados.ultimo_ciclo);

  const contagens = $("recon-contagens");
  contagens.replaceChildren();
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
      ["recon-time", formatDate(ciclo.ts_conclusao)],
      [ciclo.status === "erro" ? "recon-error" : "recon-ok", ciclo.status === "erro" ? "ERRO" : "OK"],
      ["recon-message", cycleSummary(ciclo)],
    ]) {
      const field = document.createElement("span");
      field.className = className;
      field.textContent = value;
      row.appendChild(field);
    }
    historico.appendChild(row);
  }
}


    return {refreshBadge,toggle,close,load};
  }
  const api={create};
  if(typeof module!=='undefined'&&module.exports) module.exports=api;
  root.PolarisReconciliation=api;
})(typeof window!=='undefined'?window:{});
