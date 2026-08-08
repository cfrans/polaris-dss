"""Os quatro exemplos resolvidos da especificação do modelo de confiança.

Se algum destes quebrar, a fórmula divergiu do que está documentado e do que será apresentado na
monografia — corrija o código ou atualize a especificação, mas não deixe os dois discordarem.
"""

import pytest

from src.engine.confidence import calcular, classificar, load_config
from src.engine.history import Historico, HistoricoRegra, Recorrencia
from src.engine.models import Banda, EvidenciaMetrica, EvidenciaTexto, Match


def _match(kb, rule_id, *, valor=None, limiar=None, texto_casou=True, metrica_aplicavel=True):
    regra = kb.por_id(rule_id)
    metrica = EvidenciaMetrica(
        aplicavel=metrica_aplicavel,
        cruzou=metrica_aplicavel and valor is not None and limiar is not None and valor >= limiar,
        chave=regra.condicao.metrica,
        valor=valor,
        limiar=limiar if limiar is not None else regra.condicao.limiar_uso_pct,
        operador=regra.condicao.operador,
    )
    texto = EvidenciaTexto(aplicavel=True, casou=texto_casou, regex=regra.condicao.regex_log)
    return Match(rule=regra, metrica=metrica, texto=texto)


def test_exemplo_1_disco_evidencia_completa_primeira_ocorrencia(kb, config):
    # 0,95 x 1,00 x 1,00 x 1,00 x 1,00 x 1,00
    m = _match(kb, "R001", valor=98, limiar=95, texto_casou=True)
    trace = calcular(m, kb.versao_kb, config)
    assert trace.confianca_final == pytest.approx(0.95)
    assert trace.banda is Banda.ALTA


def test_exemplo_2_cpu_raspando_sem_texto_segunda_ocorrencia(kb, config):
    # 0,85 x 0,90 (só métrica) x 0,95 (margem 0,20) x 1,00 x 0,85 (k=1)
    m = _match(kb, "R002", valor=92, limiar=90, texto_casou=False)
    hist = Historico(regra=None, recorrencia=Recorrencia(k=1))
    trace = calcular(m, kb.versao_kb, config, hist)
    assert trace.confianca_final == pytest.approx(0.6177, abs=1e-4)
    assert trace.banda is Banda.BAIXA


def test_exemplo_3_servico_caido_regra_madura(kb, config):
    # 0,92 x 1,00 x 1,00 (métrica percentual não aplicável) x 1,00 x 1,00
    m = _match(kb, "R003", metrica_aplicavel=False, texto_casou=True)
    hist = Historico(regra=HistoricoRegra(n=14, sucessos=14), recorrencia=Recorrencia(k=0))
    trace = calcular(m, kb.versao_kb, config, hist)
    assert trace.confianca_final == pytest.approx(0.92)
    assert trace.banda is Banda.ALTA


def test_exemplo_4_flapping_derruba_para_banda_baixa(kb, config):
    # Mesma evidência do exemplo 3, mas terceira ocorrência em 25 min: 0,92 x 0,60
    m = _match(kb, "R003", metrica_aplicavel=False, texto_casou=True)
    hist = Historico(regra=HistoricoRegra(n=14, sucessos=14), recorrencia=Recorrencia(k=2))
    trace = calcular(m, kb.versao_kb, config, hist)
    assert trace.confianca_final == pytest.approx(0.552)
    assert trace.banda is Banda.BAIXA
    f4 = next(f for f in trace.fatores if f.id == "F4")
    assert "flapping" in f4.motivo


def test_confianca_nunca_ultrapassa_a_base(kb, config):
    """Invariante central: nenhum fator pode elevar a confiança acima do teto do especialista."""
    for rule_id in ("R001", "R002", "R003"):
        m = _match(kb, rule_id, valor=100, limiar=1, texto_casou=True)
        hist = Historico(HistoricoRegra(n=500, sucessos=500), Recorrencia(k=0))
        trace = calcular(m, kb.versao_kb, config, hist)
        assert trace.confianca_final <= kb.por_id(rule_id).confianca_base


def test_todos_os_fatores_sao_no_maximo_um(kb, config):
    m = _match(kb, "R001", valor=99, limiar=95)
    hist = Historico(HistoricoRegra(n=50, sucessos=50), Recorrencia(k=0))
    trace = calcular(m, kb.versao_kb, config, hist)
    assert all(f.valor <= 1.0 for f in trace.fatores)


def test_historico_ruim_desconta(kb, config):
    m = _match(kb, "R001", valor=98, limiar=95)
    hist = Historico(HistoricoRegra(n=10, sucessos=5), Recorrencia(k=0))
    trace = calcular(m, kb.versao_kb, config, hist)
    f3 = next(f for f in trace.fatores if f.id == "F3")
    assert f3.valor == pytest.approx(0.75)
    assert trace.confianca_final == pytest.approx(0.7125)


def test_amostra_pequena_nao_penaliza_nem_premia(kb, config):
    m = _match(kb, "R001", valor=98, limiar=95)
    hist = Historico(HistoricoRegra(n=2, sucessos=0), Recorrencia(k=0))
    trace = calcular(m, kb.versao_kb, config, hist)
    f3 = next(f for f in trace.fatores if f.id == "F3")
    assert f3.valor == 1.0
    assert "insuficiente" in f3.motivo


def test_piso_de_confianca_respeitado(kb, config):
    cfg = dict(config)
    cfg["F4"] = {**cfg["F4"], "k2_ou_mais": 0.001}
    m = _match(kb, "R002", valor=91, limiar=90, texto_casou=False)
    hist = Historico(HistoricoRegra(n=20, sucessos=1), Recorrencia(k=5))
    trace = calcular(m, kb.versao_kb, cfg, hist)
    assert trace.confianca_final == pytest.approx(cfg["piso_confianca"])


def test_trace_serializa_para_jsonb(kb, config):
    m = _match(kb, "R001", valor=98, limiar=95)
    d = calcular(m, kb.versao_kb, config).to_dict()
    assert d["regra"] == "R001"
    assert d["banda"] == "alta"
    assert len(d["fatores"]) == 5
    assert d["evidencias"]["metrica"]["cruzou"] is True
    # As versões no trace são o que permite recalcular uma decisão antiga meses depois.
    assert d["versao_kb"] == kb.versao_kb
    assert d["versao_motor"]


@pytest.mark.parametrize(
    "valor,esperado",
    [(0.95, Banda.ALTA), (0.90, Banda.ALTA), (0.8999, Banda.MEDIA),
     (0.70, Banda.MEDIA), (0.6999, Banda.BAIXA), (0.05, Banda.BAIXA)],
)
def test_limites_das_bandas(valor, esperado, config):
    assert classificar(valor, config) is esperado


def test_config_padrao_carrega():
    cfg = load_config()
    assert cfg["bandas"]["alta"] == 0.90
    assert cfg["F1"]["dupla"] == 1.00
