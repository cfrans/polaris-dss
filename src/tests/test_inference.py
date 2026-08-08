from dataclasses import replace

import pytest

from src.engine.engine import analisar
from src.engine.inference import match_rules, rank_matches
from src.engine.models import (
    Banda,
    Condicao,
    EvidenciaMetrica,
    EvidenciaTexto,
    Match,
    Remediacao,
    Rule,
)


def test_disco_casa_com_r001(kb, alerta):
    matches = match_rules(alerta("disk_full"), kb.regras)
    assert [m.rule.id for m in matches] == ["R001"]
    m = matches[0]
    assert m.metrica.cruzou is True
    assert m.texto.casou is True
    assert "No space left on device" in m.texto.trecho


def test_cpu_casa_com_r002(kb, alerta):
    matches = match_rules(alerta("cpu_high"), kb.regras)
    assert [m.rule.id for m in matches] == ["R002"]


def test_servico_casa_com_r003(kb, alerta):
    matches = match_rules(alerta("service_down"), kb.regras)
    assert [m.rule.id for m in matches] == ["R003"]


def test_alerta_sem_regra_nao_casa(kb, alerta):
    assert match_rules(alerta("sem_regra"), kb.regras) == []


def test_sem_regra_devolve_none_em_vez_de_palpite(kb, alerta, config):
    assert analisar(alerta("sem_regra"), kb, config) is None


def test_metrica_abaixo_do_limiar_sem_texto_nao_casa(kb, alerta):
    a = alerta("cpu_high", valor=40.0, texto="rotina noturna de backup iniciada")
    assert match_rules(a, kb.regras) == []


def test_apenas_metrica_ainda_casa_mas_com_desconto(kb, alerta, config):
    a = alerta("disk_full", texto="filesystem usage above threshold")
    sug = analisar(a, kb, config)
    assert sug.rule.id == "R001"
    f1 = next(f for f in sug.trace.fatores if f.id == "F1")
    assert f1.valor == pytest.approx(0.90)
    assert sug.trace.texto.casou is False


def test_apenas_texto_ainda_casa_mas_com_desconto(kb, alerta, config):
    a = alerta("disk_full", valor=20.0)
    sug = analisar(a, kb, config)
    assert sug.rule.id == "R001"
    f1 = next(f for f in sug.trace.fatores if f.id == "F1")
    assert f1.valor == pytest.approx(0.85)


def test_severidade_minima_filtra(kb, alerta):
    a = alerta("service_down", severidade="baixa")
    assert match_rules(a, kb.regras) == []


def test_regra_desabilitada_e_ignorada(kb, alerta):
    regras = tuple(
        replace(r, habilitada=False) if r.id == "R001" else r for r in kb.regras
    )
    assert match_rules(alerta("disk_full"), regras) == []


def _regra_sintetica(rule_id, ordem, timeout, confianca):
    return Rule(
        id=rule_id,
        nome=f"Regra {rule_id}",
        condicao=Condicao(tipo_alerta="teste", regex_log=".*"),
        diagnostico="Diagnóstico sintético usado apenas para exercitar o critério de desempate.",
        remediacao=Remediacao(comando="true", rollback="true", timeout_segundos=timeout),
        confianca_base=confianca,
        ordem=ordem,
    )


def _match_sintetico(regra):
    return Match(
        rule=regra,
        metrica=EvidenciaMetrica(aplicavel=False, cruzou=False),
        texto=EvidenciaTexto(aplicavel=True, casou=True, regex=".*"),
    )


def test_desempate_por_confianca_depois_timeout_depois_ordem():
    a = _regra_sintetica("R900", ordem=0, timeout=60, confianca=0.80)
    b = _regra_sintetica("R901", ordem=1, timeout=30, confianca=0.90)
    c = _regra_sintetica("R902", ordem=2, timeout=30, confianca=0.80)
    avaliados = [
        (_match_sintetico(a), 0.80),
        (_match_sintetico(b), 0.90),
        (_match_sintetico(c), 0.80),
    ]
    ordem = [m.rule.id for m, _ in rank_matches(avaliados)]
    # b vence por confiança; entre a e c empatados, vence o de menor timeout (ação menos invasiva).
    assert ordem == ["R901", "R902", "R900"]


def test_ordenacao_e_deterministica_em_empate_total():
    regras = [_regra_sintetica(f"R9{i:02d}", ordem=i, timeout=30, confianca=0.80) for i in range(5)]
    avaliados = [(_match_sintetico(r), 0.80) for r in regras]
    primeira = [m.rule.id for m, _ in rank_matches(avaliados)]
    for _ in range(10):
        assert [m.rule.id for m, _ in rank_matches(avaliados)] == primeira


def test_sugestao_traz_comando_e_rollback_renderizados(kb, alerta, config):
    sug = analisar(alerta("service_down"), kb, config)
    assert sug.comando == "systemctl restart nginx"
    assert sug.rollback == "systemctl stop nginx"
    assert "{" not in sug.comando


def test_sugestao_de_disco_renderiza_ponto_de_montagem(kb, alerta, config):
    sug = analisar(alerta("disk_full"), kb, config)
    assert sug.comando == "disk_cleanup.sh /mnt/polaris_test"


def test_banda_alta_para_evidencia_completa(kb, alerta, config):
    assert analisar(alerta("disk_full"), kb, config).banda is Banda.ALTA
