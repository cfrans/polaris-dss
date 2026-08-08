"""Cálculo do índice de confiança.

Não é probabilidade e não deriva de inferência estatística: é um índice determinístico de
corroboração de evidências. `confianca_base` é o teto atribuído pelo especialista que escreveu a
regra, e todos os fatores são <= 1,00 — o motor apenas desconta quando a evidência é parcial ou o
histórico é adverso. O sistema nunca fica mais confiante do que o especialista autorizou.

Cada fator aplicado é registrado com o valor observado que o motivou, de modo que qualquer decisão
passada possa ser recalculada a partir do registro de auditoria.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .history import Historico
from .models import Banda, ConfidenceTrace, Fator, Match

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "src" / "knowledge_base" / "confidence_config.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def calcular(
    match: Match,
    versao_kb: str,
    config: dict[str, Any] | None = None,
    historico: Historico | None = None,
    dentro_janela_manutencao: bool = False,
) -> ConfidenceTrace:
    cfg = config or load_config()
    hist = historico or Historico()

    fatores = (
        _f1_corroboracao(match, cfg),
        _f2_margem(match, cfg),
        _f3_historico(hist, cfg),
        _f4_recorrencia(hist, cfg),
        _f5_manutencao(dentro_janela_manutencao, cfg),
    )

    produto = match.rule.confianca_base
    for fator in fatores:
        produto *= fator.valor

    final = round(max(cfg["piso_confianca"], produto), 4)

    return ConfidenceTrace(
        regra=match.rule.id,
        nome_regra=match.rule.nome,
        confianca_base=match.rule.confianca_base,
        confianca_final=final,
        banda=classificar(final, cfg),
        metrica=match.metrica,
        texto=match.texto,
        fatores=fatores,
        versao_kb=versao_kb,
    )


def classificar(confianca: float, config: dict[str, Any] | None = None) -> Banda:
    cfg = config or load_config()
    if confianca >= cfg["bandas"]["alta"]:
        return Banda.ALTA
    if confianca >= cfg["bandas"]["media"]:
        return Banda.MEDIA
    return Banda.BAIXA


def _f1_corroboracao(match: Match, cfg: dict[str, Any]) -> Fator:
    """Métrica e texto são fontes independentes. As duas concordando é o caso nominal."""
    f1 = cfg["F1"]
    m, t = match.metrica, match.texto
    metrica_ok = m.aplicavel and m.cruzou
    texto_ok = t.aplicavel and t.casou

    if metrica_ok and texto_ok:
        return Fator("F1", "corroboracao_evidencia", f1["dupla"],
                     "métrica cruzou o limiar e o padrão textual casou")

    # Regra que declara só uma das condições não é penalizada pelo que não pede.
    if metrica_ok and not t.aplicavel:
        return Fator("F1", "corroboracao_evidencia", f1["dupla"],
                     "regra sem condição textual declarada; métrica cruzou o limiar")
    if texto_ok and not m.aplicavel and match.rule.condicao.limiar_uso_pct is None:
        return Fator("F1", "corroboracao_evidencia", f1["dupla"],
                     "regra sem condição de métrica declarada; padrão textual casou")

    if metrica_ok:
        return Fator("F1", "corroboracao_evidencia", f1["somente_metrica"],
                     "apenas a métrica cruzou o limiar; padrão textual não casou")
    return Fator("F1", "corroboracao_evidencia", f1["somente_texto"],
                 "apenas o padrão textual casou; métrica ausente ou abaixo do limiar")


def _f2_margem(match: Match, cfg: dict[str, Any]) -> Fator:
    """Quanto mais o valor excede o limiar, menos ambíguo é o diagnóstico."""
    f2 = cfg["F2"]
    m = match.metrica
    if not (m.aplicavel and m.cruzou) or m.limiar is None or m.limiar >= 100:
        return Fator("F2", "margem_limiar", f2["acima"], "métrica percentual não aplicável")

    margem = min(max((m.valor - m.limiar) / (100 - m.limiar), 0.0), 1.0)
    if margem >= f2["margem_corte"]:
        return Fator("F2", "margem_limiar", f2["acima"],
                     f"margem de {margem:.2f} sobre o limiar (>= {f2['margem_corte']:.2f})")
    return Fator("F2", "margem_limiar", f2["abaixo"],
                 f"margem de {margem:.2f} sobre o limiar (abaixo de {f2['margem_corte']:.2f})")


def _f3_historico(hist: Historico, cfg: dict[str, Any]) -> Fator:
    f3 = cfg["F3"]
    if hist.regra is None:
        return Fator("F3", "historico_regra", f3["mult_boa"],
                     "histórico não consultado (fatores dependentes de auditoria desativados)")
    if hist.regra.n < f3["n_minimo"]:
        return Fator("F3", "historico_regra", f3["mult_boa"],
                     f"amostra insuficiente (n={hist.regra.n}, mínimo {f3['n_minimo']})")

    taxa = hist.regra.taxa_sucesso
    if taxa >= f3["taxa_boa"]:
        return Fator("F3", "historico_regra", f3["mult_boa"],
                     f"taxa de sucesso de {taxa:.0%} em {hist.regra.n} execuções")
    if taxa >= f3["taxa_regular"]:
        return Fator("F3", "historico_regra", f3["mult_regular"],
                     f"taxa de sucesso de {taxa:.0%} em {hist.regra.n} execuções")
    return Fator("F3", "historico_regra", f3["mult_ruim"],
                 f"taxa de sucesso de apenas {taxa:.0%} em {hist.regra.n} execuções")


def _f4_recorrencia(hist: Historico, cfg: dict[str, Any]) -> Fator:
    """Reincidência indica que a remediação anterior não sustentou: causa-raiz provavelmente outra."""
    f4 = cfg["F4"]
    janela = f4["janela_minutos"]
    if hist.recorrencia is None:
        return Fator("F4", "recorrencia", 1.00,
                     "recorrência não consultada (fatores dependentes de auditoria desativados)")

    k = hist.recorrencia.k
    if k == 0:
        return Fator("F4", "recorrencia", 1.00,
                     f"primeira ocorrência no host nos últimos {janela} min")
    if k == 1:
        return Fator("F4", "recorrencia", f4["k1"],
                     f"2ª ocorrência em {janela} min; a remediação anterior não sustentou")
    return Fator("F4", "recorrencia", f4["k2_ou_mais"],
                 f"{k + 1}ª ocorrência em {janela} min; padrão de flapping, "
                 f"causa-raiz provavelmente distinta da diagnosticada")


def _f5_manutencao(dentro_janela: bool, cfg: dict[str, Any]) -> Fator:
    f5 = cfg["F5"]
    if not f5.get("habilitado") or not dentro_janela:
        return Fator("F5", "janela_manutencao", 1.00, "não aplicável")
    return Fator("F5", "janela_manutencao", f5["dentro_janela"],
                 "evento dentro de janela de manutenção declarada; "
                 "sintoma pode ser efeito colateral de intervenção programada")
