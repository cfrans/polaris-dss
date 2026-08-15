"""Diagnóstico de conectividade e configuração.

O que se protege aqui, acima de tudo: **nenhum segredo pode aparecer na resposta**. Uma tela de
diagnóstico que exibe o token do webhook resolve um problema e cria outro.
"""

from __future__ import annotations

import pytest

from src.engine.diagnostico import (
    AVISO,
    FALHA,
    NAO_CONFIGURADO,
    OK,
    configuracao_efetiva,
    executar,
)

SEGREDOS = ("POLARIS_WEBHOOK_TOKEN", "ZABBIX_PASSWORD", "DB_PASSWORD", "ZABBIX_TOKEN")


@pytest.fixture(autouse=True)
def sem_dependencias_externas(monkeypatch):
    """Zera Zabbix e host alvo por padrão.

    Sem isso, cada chamada ao diagnóstico espera o timeout de conexão de um servidor que não existe
    no ambiente de teste, e a suíte passa de segundos a dezenas de segundos. Teste lento deixa de
    ser rodado, e teste que não se roda não protege nada.
    """
    from src.engine.config import get_settings

    monkeypatch.setenv("ZABBIX_URL", "")
    monkeypatch.setenv("TARGET_SSH_HOST", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def ambiente(monkeypatch):
    from src.engine.config import get_settings

    def configurar(**variaveis):
        for chave, valor in variaveis.items():
            monkeypatch.setenv(chave, valor)
        get_settings.cache_clear()

    yield configurar
    get_settings.cache_clear()


def _por_id(resultado, identificador):
    return next(v for v in resultado["verificacoes"] if v["id"] == identificador)


# ---------------------------------------------------------------------------
# Segredos
# ---------------------------------------------------------------------------


def test_nenhum_segredo_aparece_na_resposta(ambiente):
    ambiente(POLARIS_WEBHOOK_TOKEN="segredo-que-nao-pode-vazar",
             ZABBIX_PASSWORD="senha-do-zabbix", DB_PASSWORD="senha-do-banco")

    bruto = str(executar().to_dict())
    assert "segredo-que-nao-pode-vazar" not in bruto
    assert "senha-do-zabbix" not in bruto
    assert "senha-do-banco" not in bruto


def test_segredo_definido_informa_apenas_o_tamanho(ambiente):
    ambiente(POLARIS_WEBHOOK_TOKEN="12345678")
    item = next(c for c in configuracao_efetiva() if c["chave"] == "POLARIS_WEBHOOK_TOKEN")

    assert item["sensivel"] is True
    assert item["definido"] is True
    assert item["valor"] == "definido (8 caracteres)"


def test_segredo_ausente_e_declarado_como_nao_definido(ambiente):
    ambiente(POLARIS_WEBHOOK_TOKEN="")
    item = next(c for c in configuracao_efetiva() if c["chave"] == "POLARIS_WEBHOOK_TOKEN")

    assert item["definido"] is False
    assert item["valor"] == "não definido"


def test_todos_os_campos_sensiveis_sao_marcados():
    marcados = {c["chave"] for c in configuracao_efetiva() if c["sensivel"]}
    assert set(SEGREDOS) <= marcados


def test_valor_nao_sensivel_aparece_integro(ambiente):
    ambiente(TARGET_SSH_USER="polaris")
    item = next(c for c in configuracao_efetiva() if c["chave"] == "TARGET_SSH_USER")
    assert item["sensivel"] is False
    assert item["valor"] == "polaris"


# ---------------------------------------------------------------------------
# Verificações
# ---------------------------------------------------------------------------


def test_dependencia_nao_configurada_nao_e_falha(ambiente):
    """Zabbix e host alvo ausentes são estado legítimo em desenvolvimento, não erro."""
    ambiente(ZABBIX_URL="", TARGET_SSH_HOST="")
    resultado = executar().to_dict()

    assert _por_id(resultado, "zabbix")["estado"] == NAO_CONFIGURADO
    assert _por_id(resultado, "alvo")["estado"] == NAO_CONFIGURADO
    assert resultado["resumo"][FALHA] == 0 or _por_id(resultado, "banco")["estado"] == FALHA


def test_host_alvo_sem_chave_e_falha(ambiente):
    ambiente(TARGET_SSH_HOST="192.0.2.10", TARGET_SSH_KEY_PATH="/caminho/inexistente")
    alvo = _por_id(executar().to_dict(), "alvo")

    assert alvo["estado"] == FALHA
    assert "chave não encontrada" in alvo["detalhe"]


def test_zabbix_inacessivel_e_falha_com_causa_legivel(ambiente):
    # Porta fechada em loopback: a recusa é imediata, sem esperar timeout.
    ambiente(ZABBIX_URL="http://127.0.0.1:1/api_jsonrpc.php")
    zabbix = _por_id(executar().to_dict(), "zabbix")

    assert zabbix["estado"] == FALHA
    assert zabbix["detalhe"]
    assert "\n" not in zabbix["detalhe"]


def test_base_de_conhecimento_reporta_versao_e_regras(kb):
    base = _por_id(executar(kb).to_dict(), "base")
    assert base["estado"] == OK
    assert "v1.0.0" in base["detalhe"]
    assert "3 de 3" in base["detalhe"]


def test_base_sem_regra_habilitada_gera_atencao(kb):
    from dataclasses import replace

    desligada = replace(kb, regras=tuple(replace(r, habilitada=False) for r in kb.regras))
    base = _por_id(executar(desligada).to_dict(), "base")

    assert base["estado"] == AVISO
    assert "nenhuma regra ativa" in base["detalhe"]


def test_toda_verificacao_traz_o_mesmo_formato():
    for v in executar().to_dict()["verificacoes"]:
        assert set(v) == {"id", "nome", "estado", "detalhe", "latencia_ms"}
        assert v["estado"] in (OK, AVISO, FALHA, NAO_CONFIGURADO)
        assert v["nome"] and v["detalhe"]


def test_falha_de_uma_verificacao_nao_derruba_as_demais(ambiente):
    ambiente(ZABBIX_URL="http://127.0.0.1:1/api_jsonrpc.php",
             TARGET_SSH_HOST="192.0.2.10", TARGET_SSH_KEY_PATH="/inexistente")
    resultado = executar().to_dict()
    assert len(resultado["verificacoes"]) == 5


# ---------------------------------------------------------------------------
# Endpoint e interface
# ---------------------------------------------------------------------------


def test_endpoint_responde_com_as_tres_secoes(cliente):
    dados = cliente.get("/api/v1/diagnostico").json()
    assert set(dados) == {"verificacoes", "configuracao", "resumo"}
    assert len(dados["verificacoes"]) == 5


def test_endpoint_detecta_migracao_pendente(cliente, conn):
    """Migração pendente costuma significar container rodando imagem anterior."""
    ultima = "003"
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM schema_migrations WHERE versao = %s", (ultima,))
        registro = cur.fetchone()
    if registro is None:
        pytest.skip(f"migração {ultima} não aplicada neste banco")

    with conn.cursor() as cur:
        cur.execute("DELETE FROM schema_migrations WHERE versao = %s", (ultima,))
    conn.commit()
    try:
        migracoes = _por_id(cliente.get("/api/v1/diagnostico").json(), "migracoes")
        assert migracoes["estado"] == FALHA
        assert "pendente" in migracoes["detalhe"]
    finally:
        # Restaura o checksum original: um valor fabricado faria o aplicador de migrações abortar
        # na execução seguinte, acusando alteração de migração já aplicada.
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schema_migrations (versao, nome, checksum, aplicada_em) "
                "VALUES (%s, %s, %s, %s)",
                (registro["versao"], registro["nome"], registro["checksum"],
                 registro["aplicada_em"]),
            )
        conn.commit()


def test_interface_expoe_a_tela_de_diagnostico(cliente):
    pagina = cliente.get("/").text
    assert 'id="tela-diagnostico"' in pagina
    assert 'id="btn-diagnostico"' in pagina
    assert 'id="btn-recarregar-base"' in pagina
