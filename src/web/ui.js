(function(root) {
  "use strict";
  function reducedMotion() {
    return root.PolarisDisplay?.reducedMotion() || (typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches);
  }
  function timeZone() {return root.PolarisDisplay?.zone()??Intl.DateTimeFormat().resolvedOptions().timeZone;}
  function formatDate(value,options={}) {
    if(value==null||value===''||!Number.isFinite(+new Date(value)))return '—';
    return root.PolarisDisplay?.formatDate(value,options)??new Date(value).toLocaleString('pt-BR',options);
  }
  function formatTime(value) {return root.PolarisDisplay?.formatTime(value)??new Date(value).toLocaleTimeString('pt-BR');}
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `icons.svg#${name}`);
    svg.appendChild(use);
    return svg;
  }

  function setDisclosure(panel, trigger, open) {
    panel.classList.toggle("is-open", open);
    panel.setAttribute("aria-hidden", String(!open));
    panel.querySelector(".disclosure-clip").inert = !open;
    trigger.setAttribute("aria-expanded", String(open));
    trigger.classList.toggle("is-active", open);
  }

  const visibilityTimers = new WeakMap();
  const visibilityFrames = new WeakMap();
  function setVisibility(element, visible, duration = 220) {
    clearTimeout(visibilityTimers.get(element));
    if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(visibilityFrames.get(element));
    element.classList.add("animavel");
    if (visible) {
      element.classList.remove("oculto");
      element.inert = false;
      element.setAttribute("aria-hidden", "false");
      element.classList.add("is-hidden");
      const scheduleFrame = typeof requestAnimationFrame === "function"
        ? requestAnimationFrame : callback => { callback(); return 0; };
      visibilityFrames.set(element, scheduleFrame(() => {
        element.classList.remove("is-hidden");
        visibilityFrames.delete(element);
      }));
      return;
    }
    if (element.classList.contains("oculto")) return;
    element.inert = true;
    element.setAttribute("aria-hidden", "true");
    element.classList.add("is-hidden");
    const delay = reducedMotion() ? 0 : duration;
    visibilityTimers.set(element, setTimeout(() => {
      element.classList.add("oculto");
      visibilityTimers.delete(element);
    }, delay));
  }

  function showDialog(dialog) {
    if (!dialog.open) dialog.showModal();
    dialog.classList.remove("is-closing");
    requestAnimationFrame(() => dialog.classList.add("is-visible"));
  }

  function closeDialog(dialog) {
    if (!dialog.open || dialog.classList.contains("is-closing")) return;
    dialog.classList.add("is-closing");
    dialog.classList.remove("is-visible");
    const delay = reducedMotion() ? 0 : 200;
    setTimeout(() => { if (dialog.open) dialog.close(); dialog.classList.remove("is-closing"); }, delay);
  }

  function setConnection(element, state, checkedAt, latency) {
    const labels = {ok: "conectado", falha: "falha na conexão", aviso: "sem credenciais",
      nao_configurado: "não configurado", unknown: "não foi possível verificar"};
    const safeState = Object.hasOwn(labels, state) ? state : "unknown";
    element.dataset.state = safeState;
    const time = checkedAt ? ` · verificado às ${formatTime(checkedAt)}` : "";
    const duration = latency == null ? "" : ` · ${latency} ms`;
    const label = `${element.dataset.service}: ${labels[safeState]}${time}${duration}`;
    element.title = label;
    element.setAttribute("aria-label", label);
  }

  function formatClock(date, timeZone = root.PolarisDisplay?.zone()??Intl.DateTimeFormat().resolvedOptions().timeZone) {
    const options = {timeZone};
    return {
      time: new Intl.DateTimeFormat("pt-BR", {...options, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"}).format(date),
      date: new Intl.DateTimeFormat("pt-BR", {...options, day: "2-digit", month: "short"}).format(date),
      label: new Intl.DateTimeFormat("pt-BR", {...options, dateStyle: "full", timeStyle: "long"}).format(date),
      zone: timeZone,
    };
  }

  const api = {icon, setDisclosure, setVisibility, showDialog, closeDialog, setConnection, formatClock,formatDate,formatTime,timeZone,reducedMotion};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.PolarisUI = api;
  if (!root.document) return;
  const header = document.querySelector(".topo");
  const updateHeader = () => header.classList.toggle("is-scrolled", root.scrollY > 16);
  root.addEventListener("scroll", updateHeader, {passive: true});
  updateHeader();
  const clock = document.getElementById("header-clock");
  if (clock) {
    const updateClock = () => {
      const now = new Date();
      const value = formatClock(now);
      document.getElementById("clock-time").textContent = value.time;
      document.getElementById("clock-date").textContent = value.date;
      clock.dateTime = now.toISOString();
      clock.title = `${root.PolarisDisplay?.get().time_zone==='utc'?'Horário UTC':'Horário local do navegador'} · ${value.zone}`;
      clock.setAttribute("aria-label", `${value.label} · ${value.zone}`);
    };
    updateClock();
    root.setInterval(() => { if (!document.hidden) updateClock(); }, 1000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) updateClock(); });
    root.addEventListener('polaris:display-change',updateClock);
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
