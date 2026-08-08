"""Casamento de alertas contra a base de conhecimento.

Módulo puro: não conhece banco, HTTP nem configuração. Entrada é um `Alert` e uma lista de `Rule`;
saída é a lista de `Match` ordenada. Isso é o que permite desenvolver e testar o núcleo do sistema
sem Zabbix, sem banco e sem interface.
"""

from __future__ import annotations

import re

from .models import (
    SEVERIDADES,
    Alert,
    EvidenciaMetrica,
    EvidenciaTexto,
    Match,
    Rule,
)

_OPERADORES = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}


def match_rules(alert: Alert, regras: tuple[Rule, ...] | list[Rule]) -> list[Match]:
    """Retorna as regras compatíveis com o alerta, sem ordenar por confiança.

    A ordenação final depende do cálculo de confiança e é feita em `rank_matches`, já que o motor
    precisa do trace de cada candidata para decidir a vencedora.
    """
    encontrados: list[Match] = []
    for regra in regras:
        if not regra.habilitada:
            continue
        if regra.condicao.tipo_alerta != alert.tipo_alerta:
            continue
        if not _severidade_atendida(regra, alert):
            continue

        metrica = _avaliar_metrica(regra, alert)
        texto = _avaliar_texto(regra, alert)

        # A regra casa se ao menos uma das condições declaradas foi satisfeita. Evidência parcial
        # não impede o diagnóstico, mas desconta confiança no fator F1.
        if (metrica.aplicavel and metrica.cruzou) or (texto.aplicavel and texto.casou):
            encontrados.append(Match(rule=regra, metrica=metrica, texto=texto))
    return encontrados


def rank_matches(avaliados: list[tuple[Match, float]]) -> list[tuple[Match, float]]:
    """Ordena candidatas: maior confiança, depois ação menos invasiva, depois ordem de declaração.

    O terceiro critério existe para garantir saída determinística mesmo com empate total — sem ele,
    duas execuções sobre a mesma entrada poderiam divergir, o que contradiz a premissa do trabalho.
    """
    return sorted(
        avaliados,
        key=lambda par: (-par[1], par[0].rule.remediacao.timeout_segundos, par[0].rule.ordem),
    )


def _severidade_atendida(regra: Rule, alert: Alert) -> bool:
    if regra.severidade_minima is None or alert.severidade is None:
        return True
    if alert.severidade not in SEVERIDADES or regra.severidade_minima not in SEVERIDADES:
        return True
    return SEVERIDADES.index(alert.severidade) >= SEVERIDADES.index(regra.severidade_minima)


def _avaliar_metrica(regra: Rule, alert: Alert) -> EvidenciaMetrica:
    limiar = regra.condicao.limiar_uso_pct
    aplicavel = limiar is not None and alert.valor is not None
    if not aplicavel:
        return EvidenciaMetrica(
            aplicavel=False,
            cruzou=False,
            chave=regra.condicao.metrica,
            valor=alert.valor,
            limiar=limiar,
            operador=regra.condicao.operador,
        )
    comparar = _OPERADORES[regra.condicao.operador]
    return EvidenciaMetrica(
        aplicavel=True,
        cruzou=comparar(alert.valor, limiar),
        chave=regra.condicao.metrica,
        valor=alert.valor,
        limiar=limiar,
        operador=regra.condicao.operador,
    )


def _avaliar_texto(regra: Rule, alert: Alert) -> EvidenciaTexto:
    padrao = regra.condicao.regex_log
    if padrao is None:
        return EvidenciaTexto(aplicavel=False, casou=False)
    achado = re.search(padrao, alert.texto or "", re.IGNORECASE | re.DOTALL)
    return EvidenciaTexto(
        aplicavel=True,
        casou=achado is not None,
        regex=padrao,
        trecho=achado.group(0)[:200] if achado else None,
    )
