"""Orquestração do motor: alerta entra, sugestão explicada sai.

O motor termina aqui. Ele nunca executa a remediação — quem dispara a execução é o endpoint de
decisão, e só depois de gravar a aprovação humana no banco.
"""

from __future__ import annotations

from typing import Any

from .confidence import calcular, load_config
from .history import Historico
from .inference import match_rules, rank_matches
from .knowledge_base import KnowledgeBase
from .models import Alert, Suggestion


def analisar(
    alert: Alert,
    kb: KnowledgeBase,
    config: dict[str, Any] | None = None,
    historico: Historico | None = None,
) -> Suggestion | None:
    """Retorna a sugestão de maior confiança, ou None quando nenhuma regra é compatível.

    Ausência de regra compatível não é erro: é o sistema reconhecendo que não sabe. O caso é
    registrado como `no_match` e apresentado ao operador sem sugestão, nunca com um palpite.
    """
    cfg = config or load_config()

    candidatas = match_rules(alert, kb.regras)
    if not candidatas:
        return None

    avaliadas = [
        (m, calcular(m, kb.versao_kb, cfg, historico).confianca_final) for m in candidatas
    ]
    ordenadas = rank_matches(avaliadas)

    vencedora = ordenadas[0][0]
    trace = calcular(vencedora, kb.versao_kb, cfg, historico)

    descartadas = tuple(
        {"regra": m.rule.id, "nome_regra": m.rule.nome, "confianca": conf}
        for m, conf in ordenadas[1:]
    )
    if descartadas:
        trace = _com_descartadas(trace, descartadas)

    return Suggestion(
        alert=alert,
        rule=vencedora.rule,
        comando=vencedora.rule.render(vencedora.rule.remediacao.comando),
        rollback=vencedora.rule.render(vencedora.rule.remediacao.rollback),
        trace=trace,
    )


def _com_descartadas(trace, descartadas):
    from dataclasses import replace

    return replace(trace, regras_candidatas_descartadas=descartadas)
