/* Display helpers only: script content is never interpreted as HTML or executed. */
(function (scope) {
  "use strict";
  const descriptions = {
    "collect_evidence.py": {
      title: "Inspecionar o alvo antes da decisão",
      purpose: "Consulta metadados de logs do volume autorizado, identidade de processo ou estado e padrões conhecidos do nginx, com limites de leitura e tempo.",
      effect: "Somente leitura. Não comprime, remove, encerra ou reinicia. Exporta padrões reconhecidos, sem copiar logs integrais.",
    },
    "apply_action.py": {
      title: "Executar a ação específica aprovada",
      purpose: "Recebe a operação e o alvo do plano aprovado, confere identidade e validade e executa somente aquela ação.",
      effect: "Pode comprimir um log fechado, excluir um gzip antigo, encerrar o processo identificado ou iniciar/reiniciar nginx. Mudança do alvo recusa a ação; não escolhe outro silenciosamente.",
    },
    "disk_cleanup.sh": {
      title: "Liberar espaço em disco",
      purpose: "Remove o arquivo .gz mais antigo no ponto autorizado, independentemente da idade; tenta rotacionar logs e remove os demais .gz com mais de sete dias.",
      effect: "Altera arquivos e pode removê-los permanentemente. A seleção não verifica o conteúdo. Não há restauração automática; confira o volume antes de aprovar.",
    },
    "kill_target_process.sh": {
      title: "Encerrar um processo com alto consumo de CPU",
      purpose: "Seleciona um candidato pelo consumo de CPU e só prossegue se o nome do processo estiver na lista autorizada.",
      effect: "Envia SIGTERM e pode usar SIGKILL se o processo não encerrar. Trabalho não salvo pode ser perdido; o processo não é reiniciado automaticamente.",
    },
    "verify_disk.sh": {
      title: "Conferir o uso do disco",
      purpose: "Consulta o uso do ponto de montagem e compara com o limite de saúde informado no script.",
      effect: "Somente consulta. Não remove arquivos nem libera espaço; o resultado indica se o uso está abaixo do limite.",
    },
    "verify_cpu.sh": {
      title: "Conferir o uso da CPU",
      purpose: "Mede o uso atual de CPU e compara com o limite de saúde informado no script.",
      effect: "Somente consulta. Não encerra processos; o resultado indica se o uso está abaixo do limite.",
    },
    "verify_service.sh": {
      title: "Conferir o estado de um serviço",
      purpose: "Consulta se o serviço informado está ativo.",
      effect: "Somente consulta. Não inicia nem reinicia o serviço; a ação de reiniciar nginx pertence à remediação de R003.",
    },
  };

  function describeScript(name) {
    return Object.hasOwn(descriptions, name) ? descriptions[name] : {
      title: "Script do catálogo",
      purpose: "Não há descrição específica para este script. Confira seu conteúdo integral.",
      effect: "Os efeitos dependem do código e dos parâmetros utilizados; não presuma que seja somente consulta.",
    };
  }

  function tokenizeShell(source) {
    const tokens = [];
    // Lightweight highlighting, not a Bash parser. Every character is preserved.
    const pattern = /(#[^\n]*)|("(?:\\[\s\S]|[^"\\])*"|'[^']*')|(\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\$[0-9@?#])|\b(if|then|else|elif|fi|for|while|do|done|case|in|esac|function|exit|return)\b|([|&;<>]+)|\b(\d+)\b/g;
    let offset = 0;
    for (const match of source.matchAll(pattern)) {
      if (match.index > offset) tokens.push({text: source.slice(offset, match.index), kind: "plain"});
      const kind = match[1] ? "comment" : match[2] ? "string" : match[3] ? "variable"
        : match[4] ? "keyword" : match[5] ? "operator" : "number";
      tokens.push({text: match[0], kind});
      offset = match.index + match[0].length;
    }
    if (offset < source.length) tokens.push({text: source.slice(offset), kind: "plain"});
    return tokens;
  }

  function renderScript(element, source, colored = true) {
    if (!colored) { element.textContent = source; return; }
    const fragment = document.createDocumentFragment();
    for (const token of tokenizeShell(source)) {
      const span = document.createElement("span");
      span.className = `shell-${token.kind}`;
      span.textContent = token.text;
      fragment.appendChild(span);
    }
    element.replaceChildren(fragment);
  }

  scope.PolarisScriptViewer = {describeScript, tokenizeShell, renderScript};
})(typeof module !== "undefined" ? module.exports : window);
