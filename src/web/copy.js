/* Shared copy buttons. The Clipboard API exists only in secure contexts (HTTPS or localhost);
   a paired laboratory browser over plain HTTP falls back to a temporary selection. */
(function(root) {
  "use strict";

  async function copyText(text, doc = root.document) {
    if (!text) return false;
    try {
      if (root.isSecureContext !== false && root.navigator?.clipboard?.writeText) {
        await root.navigator.clipboard.writeText(text);
        return true;
      }
    } catch { /* fall back below */ }
    if (!doc?.body || typeof doc.execCommand !== "function") return false;
    const area = doc.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.opacity = "0";
    doc.body.appendChild(area);
    area.select();
    let copied = false;
    try { copied = doc.execCommand("copy"); } catch { copied = false; }
    area.remove();
    return copied;
  }

  function sourceValue(button, doc) {
    if (button.dataset.copyField) return doc.getElementById(button.dataset.copyField)?.value || "";
    return (doc.getElementById(button.dataset.copy)?.textContent || "").trim();
  }

  /* Buttons declare [data-copy="element-id"] (text) or [data-copy-field="input-id"] (value),
     plus an optional [data-copy-message] confirmation. Binding twice is harmless. */
  function bind(scope = root.document, onCopy) {
    const doc = root.document;
    scope.querySelectorAll("[data-copy], [data-copy-field]").forEach(button => {
      if (button.dataset.copyBound) return;
      button.dataset.copyBound = "true";
      button.addEventListener("click", async () => {
        const value = sourceValue(button, doc);
        const copied = await copyText(value, doc);
        const message = copied ? button.dataset.copyMessage || "Copiado para a área de transferência."
          : value ? "Não foi possível copiar. Selecione o texto e copie manualmente."
            : "Nada para copiar ainda.";
        root.PolarisToast?.(message);
        button.classList.toggle("is-copied", copied);
        button.title = copied ? "Copiado" : "Copiar";
        root.setTimeout(() => { button.classList.remove("is-copied"); button.title = "Copiar"; }, 2200);
        onCopy?.(copied, button, message);
      });
    });
  }

  const api = {copyText, bind};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.PolarisCopy = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
