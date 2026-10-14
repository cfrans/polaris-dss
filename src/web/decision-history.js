(function(root) {
  "use strict";
  const namespace = "http://www.w3.org/2000/svg";
  const number = value => value.toLocaleString("pt-BR");

  function validateHistory(data, period) {
    if (!data || data.periodo !== period || data.fuso !== "UTC"
        || !["hour", "day"].includes(data.agrupamento) || !Array.isArray(data.series)
        || !data.series.length || data.series.length > 32
        || !Number.isFinite(Date.parse(data.inicio)) || !Number.isFinite(Date.parse(data.fim))
        || Date.parse(data.inicio) >= Date.parse(data.fim)) throw new Error("Invalid decision history");
    let previous = -Infinity;
    const totals = {aprovadas: 0, rejeitadas: 0};
    for (const row of data.series) {
      const time = Date.parse(row.inicio);
      if (!Number.isFinite(time) || time <= previous || time >= Date.parse(data.fim)) throw new Error("Invalid bucket");
      previous = time;
      for (const key of Object.keys(totals)) {
        if (!Number.isSafeInteger(row[key]) || row[key] < 0) throw new Error("Invalid count");
        totals[key] += row[key];
      }
    }
    for (const key of Object.keys(totals)) {
      if (!Number.isSafeInteger(totals[key]) || totals[key] !== data.totais?.[key]) throw new Error("Invalid total");
    }
    return data;
  }

  function tickStep(maximum) {
    const rough = Math.max(1, maximum / 4);
    const power = 10 ** Math.floor(Math.log10(rough));
    return [1, 2, 5, 10].map(value => value * power).find(value => value >= rough);
  }

  function bucketLabel(value, grouping) {
    return new Date(value).toLocaleString("pt-BR", {timeZone: "UTC", day: "2-digit", month: "2-digit",
      ...(grouping === "hour" ? {hour: "2-digit", minute: "2-digit"} : {})});
  }

  function renderChart(document, container, data) {
    const svg = document.createElementNS(namespace, "svg");
    const node = (tag, attributes, text) => {
      const element = document.createElementNS(namespace, tag);
      for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
      if (text != null) element.textContent = text;
      return element;
    };
    svg.setAttribute("viewBox", "0 0 880 244");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Decisões em UTC: ${number(data.totais.aprovadas)} aprovadas e ${number(data.totais.rejeitadas)} rejeitadas. Valores disponíveis na tabela abaixo.`);
    const left = 48, top = 16, width = 812, height = 178;
    const maximum = Math.max(...data.series.map(row => row.aprovadas + row.rejeitadas), 1);
    const step = tickStep(maximum), ceiling = Math.ceil(maximum / step) * step;
    for (let tick = 0; tick <= ceiling; tick += step) {
      const y = top + height - tick / ceiling * height;
      svg.appendChild(node("line", {x1: left, x2: left + width, y1: y, y2: y, class: "history-grid"}));
      svg.appendChild(node("text", {x: left - 12, y: y + 4, "text-anchor": "end", class: "history-axis"}, number(tick)));
    }
    const stride = width / data.series.length;
    const barWidth = Math.min(36, stride * 0.62);
    data.series.forEach((row, index) => {
      const x = left + stride * (index + 0.5);
      const approvedHeight = row.aprovadas / ceiling * height;
      const rejectedHeight = row.rejeitadas / ceiling * height;
      const group = node("g", {class: "history-bar"});
      group.appendChild(node("title", {}, `${bucketLabel(row.inicio, data.agrupamento)} UTC: ${number(row.aprovadas)} aprovadas, ${number(row.rejeitadas)} rejeitadas`));
      if (row.aprovadas) group.appendChild(node("rect", {x: x - barWidth / 2,
        y: top + height - approvedHeight, width: barWidth, height: approvedHeight, class: "history-bar-approved"}));
      if (row.rejeitadas) group.appendChild(node("rect", {x: x - barWidth / 2,
        y: top + height - approvedHeight - rejectedHeight, width: barWidth, height: rejectedHeight, class: "history-bar-rejected"}));
      if (!row.aprovadas && !row.rejeitadas) group.appendChild(node("circle", {cx: x, cy: top + height, r: 2, class: "history-zero"}));
      svg.appendChild(group);
      const labelEvery = Math.ceil(data.series.length / 5);
      if (index % labelEvery === 0 || index === data.series.length - 1) {
        // Do not overlap the last two labels on a short final interval.
        if (index !== data.series.length - 1 && data.series.length - 1 - index < labelEvery * 0.65) return;
        const label = data.agrupamento === "hour"
          ? new Date(row.inicio).toLocaleTimeString("pt-BR", {timeZone: "UTC", hour: "2-digit", minute: "2-digit"})
          : bucketLabel(row.inicio, "day");
        svg.appendChild(node("text", {x, y: 224, "text-anchor": "middle", class: "history-axis"}, label));
      }
    });
    container.replaceChildren(svg);
  }

  if (typeof module !== "undefined" && module.exports) module.exports = {validateHistory, tickStep, bucketLabel, renderChart};
  if (!root.document) return;
  const byId = id => root.document.getElementById(id);
  if (!byId("decision-history")) return;
  const period = byId("history-period");
  let requestId = 0, busy = false, controller;

  function clear() {
    byId("history-chart").replaceChildren();
    byId("history-values").replaceChildren();
    byId("history-details").classList.add("oculto");
    byId("history-approved").textContent = "—";
    byId("history-rejected").textContent = "—";
    byId("history-caption").textContent = "Contagem operacional; não representa os KPIs do experimento.";
  }

  async function refresh(force = false) {
    if (!force && (busy || root.document.hidden || byId("placeholder").classList.contains("oculto"))) return;
    const request = ++requestId;
    controller?.abort();
    controller = new AbortController();
    const activeController = controller;
    const selectedPeriod = period.value;
    busy = true;
    const timeout = setTimeout(() => activeController.abort(), 15000);
    if (force) {
      clear();
      byId("history-message").textContent = "Consultando decisões…";
      byId("history-message").classList.remove("oculto");
    }
    try {
      const response = await fetch(`/api/v1/historico-decisoes?period=${encodeURIComponent(selectedPeriod)}`, {signal: activeController.signal});
      if (!response.ok) throw new Error("History unavailable");
      const data = validateHistory(await response.json(), selectedPeriod);
      if (request !== requestId) return;
      renderChart(root.document, byId("history-chart"), data);
      byId("history-approved").textContent = number(data.totais.aprovadas);
      byId("history-rejected").textContent = number(data.totais.rejeitadas);
      const total = data.totais.aprovadas + data.totais.rejeitadas;
      byId("history-message").textContent = "Nenhuma aprovação ou rejeição registrada neste período.";
      byId("history-message").classList.toggle("oculto", total > 0);
      const rows = data.series.map(row => {
        const tr = root.document.createElement("tr");
        for (const value of [bucketLabel(row.inicio, data.agrupamento), number(row.aprovadas), number(row.rejeitadas)]) {
          const td = root.document.createElement("td"); td.textContent = value; tr.appendChild(td);
        }
        return tr;
      });
      byId("history-values").replaceChildren(...rows);
      byId("history-details").classList.remove("oculto");
      byId("history-caption").textContent = `${bucketLabel(data.inicio, "hour")} a ${bucketLabel(data.fim, "hour")} UTC · por ${data.agrupamento === "hour" ? "hora" : "dia"}; intervalos das extremidades podem ser parciais. Contagem operacional, sem relação com os KPIs do experimento.`;
    } catch {
      if (request !== requestId) return;
      clear();
      byId("history-message").textContent = "Não foi possível consultar o histórico. Nova tentativa em até 60 segundos.";
      byId("history-message").classList.remove("oculto");
    } finally {
      clearTimeout(timeout);
      if (request === requestId) busy = false;
    }
  }
  period.addEventListener("change", () => refresh(true));
  byId("brand-home").addEventListener("click", event => {
    if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && !event.button) refresh(true);
  });
  root.document.addEventListener("visibilitychange", () => refresh());
  refresh(true);
  setInterval(refresh, 60000);
})(typeof window === "undefined" ? globalThis : window);
