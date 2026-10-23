(function(root) {
  "use strict";
  const maxAge = 300000;

  function recentSample(sample, now = Date.now()) {
    if (!sample || typeof sample.percentual !== "number" || !Number.isFinite(sample.percentual)
        || sample.percentual < 0 || sample.percentual > 100) return null;
    const age = now - Date.parse(sample.coletado_em);
    return Number.isFinite(age) && age >= 0 && age <= maxAge ? sample : null;
  }

  function percentage(value) { return `${value.toLocaleString("pt-BR", {maximumFractionDigits: 1})}%`; }

  if (typeof module !== "undefined" && module.exports) module.exports = {recentSample, percentage};
  if (!root.document) return;
  const byId = id => document.getElementById(id);
  const widget = byId("server-widget");
  if (!widget) return;
  const trigger = byId("server-toggle");
  const panel = byId("server-panel");
  let busy = false;
  let current = null;
  let checkedAt = 0;

  function renderMetric(name, sample) {
    const value = recentSample(sample);
    const bar = byId(`server-${name}-bar`);
    byId(`server-${name}-value`).textContent = value ? percentage(value.percentual) : "—";
    bar.firstElementChild.style.width = value ? `${value.percentual}%` : "0%";
    bar.dataset.available = String(Boolean(value));
    bar.setAttribute("role", value ? "meter" : "img");
    bar.setAttribute("aria-label", `${name === "cpu" ? "CPU" : "Memória"} em uso${value ? "" : ": sem dados recentes"}`);
    if (value) {
      bar.setAttribute("aria-valuemin", "0");
      bar.setAttribute("aria-valuemax", "100");
      bar.setAttribute("aria-valuenow", String(value.percentual));
    } else {
      for (const attribute of ["aria-valuenow", "aria-valuemin", "aria-valuemax"]) bar.removeAttribute(attribute);
    }
    bar.setAttribute("aria-valuetext", value ? percentage(value.percentual) : "Sem dados recentes");
    byId(`server-${name}-time`).textContent = value
      ? `Coleta às ${root.PolarisUI.formatTime(value.coletado_em)}` : "Sem coleta recente";
    return value;
  }

  function render(data) {
    const cpu = renderMetric("cpu", data?.cpu);
    const memory = renderMetric("memory", data?.memoria);
    byId("server-summary").textContent = cpu || memory
      ? `CPU ${cpu ? percentage(cpu.percentual) : "—"} · RAM ${memory ? percentage(memory.percentual) : "—"}` : "Sem dados";
    byId("server-source").textContent = data?.host ? `${data.host} · Zabbix` : "Métricas pelo Zabbix";
    byId("server-message").textContent = data?.detalhe || "Não foi possível consultar as métricas. Tente atualizar.";
    if (data?.estado === "ok" && (!cpu || !memory)) {
      byId("server-message").textContent = "Aguardando uma coleta recente do Zabbix.";
    }
    trigger.title = `Recursos do servidor Polaris: ${byId("server-summary").textContent}`;
    trigger.setAttribute("aria-label", trigger.title);
  }

  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    byId("server-refresh").disabled = true;
    const controller = new AbortController();
    const timeout = root.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await root.fetch("/api/v1/servidor", {signal: controller.signal});
      if (!response.ok) throw new Error("Metrics unavailable");
      current = await response.json();
    } catch {
      current = null;
    } finally {
      root.clearTimeout(timeout);
      checkedAt = Date.now();
      render(current);
      busy = false;
      byId("server-refresh").disabled = false;
    }
  }

  function close() { root.PolarisUI.setDisclosure(panel, trigger, false); }
  trigger.addEventListener("click", () => {
    const open = trigger.getAttribute("aria-expanded") !== "true";
    root.PolarisUI.setDisclosure(panel, trigger, open);
    if (open) {
      render(current);
      if (Date.now() - checkedAt >= 30000) refresh();
    }
  });
  byId("server-refresh").addEventListener("click", refresh);
  document.addEventListener("click", event => { if (!widget.contains(event.target)) close(); });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && trigger.getAttribute("aria-expanded") === "true") {
      close();
      trigger.focus();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { render(current); if (Date.now() - checkedAt >= 30000) refresh(); }
  });
  root.addEventListener('polaris:display-change',()=>render(current));
  refresh();
  root.setInterval(() => { if (!document.hidden) { render(current); refresh(); } }, 30000);
})(typeof globalThis !== "undefined" ? globalThis : this);
