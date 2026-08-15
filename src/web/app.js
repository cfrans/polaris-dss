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
};

const $ = (id) => document.getElementById(id);

async function api(caminho, opcoes = {}) {
  const resposta = await fetch(caminho, {
    headers: { "Content-Type": "application/json" },
    ...opcoes,
  });
  const corpo = resposta.status === 204 ? null : await resposta.json();
  if (!resposta.ok) {
    throw new Error(corpo?.mensagem || `Falha na requisição (${resposta.status})`);
  }
  return corpo;
}

const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);

/* ---------- saúde ---------- */

async function atualizarSaude() {
  try {
    const s = await api("/health");
    $("estado-kb").textContent = `base v${s.versao_kb ?? "—"}`;
    $("estado-db").textContent = `banco ${s.db}`;
    $("estado-db").classList.toggle("ruim", s.db !== "ok");
    // O botão de simulação vem da flag de saúde. Sondar o endpoint de simulação criaria um
    // incidente a cada carregamento da página e contaminaria a trilha de auditoria.
    estado.debug = s.debug === true;
    $("btn-simular").classList.toggle("oculto", !estado.debug);
  } catch {
    $("estado-db").textContent = "banco indisponível";
    $("estado-db").classList.add("ruim");
  }
}

/* ---------- lista ---------- */

async function carregarLista() {
  let dados;
  try {
    dados = await api("/api/v1/incidentes?status=pendente&limit=50");
  } catch {
    return;
  }

  $("contador").textContent = dados.total;
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
  estado.selecionado = id;
  estado.confirmandoBandaBaixa = false;

  const inc = await api(`/api/v1/incidentes/${id}`);

  $("placeholder").classList.add("oculto");
  $("detalhe").classList.remove("oculto");

  $("d-regra").textContent = inc.regra ?? "—";
  $("d-nome").textContent = inc.nome_regra ?? "Incidente sem heurística formalizada";
  $("d-host").textContent = `${inc.hostname ?? "—"} · evento ${inc.id_evento ?? "—"} · severidade ${inc.severidade ?? "—"}`;

  $("d-confianca").textContent = pct(inc.confianca);
  $("d-confianca").className = `confianca-valor cor-${inc.banda ?? ""}`;
  $("d-banda").textContent = inc.banda ?? "—";
  $("d-banda").className = `confianca-banda banda-${inc.banda ?? ""}`;
  $("d-base").textContent = `teto da regra: ${pct(
    inc.fatores.length ? inc.confianca / produtoFatores(inc.fatores) : null
  )}`;

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
  const exigeConfirmacao = inc.banda === "baixa";
  aprovar.classList.toggle("atencao", exigeConfirmacao);
  aprovar.textContent = exigeConfirmacao ? "Aprovar mesmo assim" : "Aprovar e executar";

  aprovar.onclick = () => {
    if (exigeConfirmacao && !estado.confirmandoBandaBaixa) {
      estado.confirmandoBandaBaixa = true;
      $("confirmacao").textContent =
        "Confiança baixa. Clique novamente para confirmar a execução sob sua responsabilidade.";
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
  if (inc.status !== "pendente" || estado.exibicaoRegistrada.has(inc.id)) return;
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
      body: JSON.stringify({ aprovado, operador: OPERADOR, motivo }),
    });
  } catch (erro) {
    alert(erro.message);
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
  corpo.innerHTML = `<p class="resultado-status cor-media">ainda em execução</p>`;
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
$("btn-diagnostico").addEventListener("click", abrirDiagnostico);
$("btn-fechar-diagnostico").addEventListener("click", fecharDiagnostico);
$("btn-reverificar").addEventListener("click", carregarDiagnostico);
$("btn-recarregar-base").addEventListener("click", recarregarBase);

atualizarSaude();
carregarLista();
setInterval(carregarLista, INTERVALO_LISTA_MS);
setInterval(atualizarSaude, 15000);
