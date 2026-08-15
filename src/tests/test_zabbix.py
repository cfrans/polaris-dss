"""Normalização de eventos do Zabbix e laço de reconciliação.

Nenhum teste aqui fala com um Zabbix real: a normalização é função pura, e a reconciliação recebe
um cliente dublê. Os payloads reproduzem o que o media type de `infra/zabbix/` envia.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.engine.zabbix_client import (
    ZabbixClient,
    ZabbixError,
    classificar,
    extrair_tags,
    interpretar_data,
    normalizar_webhook,
    traduzir_severidade,
    valor_numerico,
)

WEBHOOK_DISCO = {
    "event_id": "80231",
    "event_time": "2026.10.14 18:22:01",
    "host": "vm-alvo",
    "host_ip": "192.168.0.152",
    "trigger": "/mnt/polaris_test: Disk space is critically low (used > 95%)",
    "severity": "High",
    "item_key": "vfs.fs.size[/mnt/polaris_test,pused]",
    "item_value": "97.4 %",
    "tags": "polaris_tipo: disk_full, scope: capacity",
}


def test_normaliza_evento_de_disco():
    alerta = normalizar_webhook(WEBHOOK_DISCO)
    assert alerta.tipo_alerta == "disk_full"
    assert alerta.hostname == "vm-alvo"
    assert alerta.id_evento == "80231"
    assert alerta.valor == pytest.approx(97.4)
    assert alerta.severidade == "alta"
    assert alerta.metrica == "vfs.fs.size[/mnt/polaris_test,pused]"
    assert "Disk space is critically low" in alerta.texto
    assert alerta.ts_deteccao == datetime(2026, 10, 14, 18, 22, 1, tzinfo=timezone.utc)


def test_evento_normalizado_casa_com_a_regra(kb, config, monkeypatch):
    """O caminho que importa: o que chega do Zabbix precisa disparar a heurística."""
    from src.engine.engine import analisar

    alerta = normalizar_webhook(WEBHOOK_DISCO)
    sugestao = analisar(alerta, kb, config)
    assert sugestao is not None
    assert sugestao.rule.id == "R001"


@pytest.mark.parametrize("bruto,esperado", [
    ("polaris_tipo: cpu_high, scope: performance", {"polaris_tipo": "cpu_high", "scope": "performance"}),
    ({"polaris_tipo": "disk_full"}, {"polaris_tipo": "disk_full"}),
    ([{"tag": "polaris_tipo", "value": "service_down"}], {"polaris_tipo": "service_down"}),
    ("", {}),
    (None, {}),
])
def test_extrai_tags_dos_tres_formatos(bruto, esperado):
    """A macro entrega string; o JSON-RPC entrega lista; o corpo manual pode entregar dicionário."""
    assert extrair_tags(bruto) == esperado


def test_tag_tem_precedencia_sobre_a_heuristica():
    tags = {"polaris_tipo": "service_down"}
    assert classificar(tags, "vfs.fs.size[/,pused]") == "service_down"


@pytest.mark.parametrize("item_key,esperado", [
    ("vfs.fs.size[/mnt/polaris_test,pused]", "disk_full"),
    ("system.cpu.util", "cpu_high"),
    ("proc.num[nginx]", "service_down"),
    ("net.tcp.service[http]", "service_down"),
    ("agent.ping", "desconhecido"),
])
def test_heuristica_por_chave_de_item(item_key, esperado):
    assert classificar({}, item_key) == esperado


@pytest.mark.parametrize("bruto,esperado", [
    (0, "baixa"), (2, "media"), (4, "alta"), (5, "critica"),
    ("Warning", "media"), ("Disaster", "critica"), ("high", "alta"),
    ("", None), (None, None), ("inexistente", None),
])
def test_traduz_severidade_em_codigo_e_rotulo(bruto, esperado):
    assert traduzir_severidade(bruto) == esperado


@pytest.mark.parametrize("bruto,esperado", [
    ("97.4 %", 97.4), ("0", 0.0), ("up (1)", 1.0), ("1,5 GB", 1.5),
    (92, 92.0), ("-3", -3.0), ("sem numero", None), (None, None),
])
def test_extrai_valor_numerico(bruto, esperado):
    assert valor_numerico(bruto) == (pytest.approx(esperado) if esperado is not None else None)


@pytest.mark.parametrize("bruto", ["2026.10.14 18:22:01", "2026-10-14 18:22:01", 1760466121])
def test_interpreta_data_em_varios_formatos(bruto):
    assert interpretar_data(bruto) is not None


def test_evento_incompleto_nao_quebra():
    """Falta de campo não pode descartar um incidente que ainda casaria pelo texto."""
    alerta = normalizar_webhook({"host": "vm-alvo", "trigger": "nginx is not running"})
    assert alerta.hostname == "vm-alvo"
    assert alerta.valor is None
    assert alerta.severidade is None
    assert alerta.tipo_alerta == "desconhecido"


# ---------------------------------------------------------------------------
# Reconciliação
# ---------------------------------------------------------------------------


class ClienteDuble:
    def __init__(self, alertas):
        self._alertas = alertas

    def alertas_abertos(self):
        return list(self._alertas)


def test_reconciliacao_recupera_evento_perdido(conn, kb, config):
    from src.engine.reconciliacao import reconciliar

    cliente = ClienteDuble([normalizar_webhook({**WEBHOOK_DISCO, "event_id": "rec-1"})])
    resultado = reconciliar(conn, cliente, kb, config)

    assert resultado.recuperados == 1
    assert resultado.ja_conhecidos == 0
    assert len(queries_pendentes(conn)) == 1


def test_reconciliacao_nao_duplica_o_que_ja_existe(conn, kb, config):
    from src.engine.reconciliacao import reconciliar

    cliente = ClienteDuble([normalizar_webhook({**WEBHOOK_DISCO, "event_id": "rec-2"})])
    reconciliar(conn, cliente, kb, config)
    segundo = reconciliar(conn, cliente, kb, config)

    assert segundo.recuperados == 0
    assert segundo.ja_conhecidos == 1
    assert len(queries_pendentes(conn)) == 1


def test_reconciliacao_encerra_incidente_resolvido_na_origem(conn, kb, config):
    """Problema que sumiu do Zabbix antes da decisão não pode ficar pendente para sempre."""
    from src.db import queries
    from src.engine.reconciliacao import reconciliar

    cliente = ClienteDuble([normalizar_webhook({**WEBHOOK_DISCO, "event_id": "rec-3"})])
    reconciliar(conn, cliente, kb, config)

    vazio = ClienteDuble([])
    resultado = reconciliar(conn, vazio, kb, config)

    assert resultado.encerrados == 1
    registro = queries.obter_incidente(conn, queries.listar_incidentes(conn, status=None)[0]["id"])
    assert registro["status_execucao"] == "encerrado_na_origem"
    # Não houve decisão nem execução: não pode contar como acerto de heurística no KPI 03.
    assert registro["decisao_humana"] is None


def queries_pendentes(conn):
    from src.db import queries
    return queries.listar_incidentes(conn, status="pendente")


# ---------------------------------------------------------------------------
# Cliente JSON-RPC
# ---------------------------------------------------------------------------


def test_cliente_sem_credenciais_falha_claramente():
    cliente = ZabbixClient(url="http://exemplo/api_jsonrpc.php")
    with pytest.raises(ZabbixError, match="sem credenciais"):
        cliente.autenticar()


def test_cliente_usa_token_quando_disponivel():
    cliente = ZabbixClient(url="http://exemplo/api_jsonrpc.php", token="abc123")
    assert cliente.autenticar() == "abc123"
