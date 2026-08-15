"""Laço de reconciliação com a API do Zabbix.

O webhook é o caminho primário de ingestão. Este laço cobre o que ele não garante: eventos
disparados enquanto o Polaris estava fora do ar, e incidentes que o Zabbix já resolveu na origem
mas continuam pendentes na fila de decisão.

A função `reconciliar` é síncrona e sem estado próprio — recebe tudo o que precisa e devolve o que
fez, o que a torna testável com um cliente dublê.

    python -m src.engine.reconciliacao          executa um ciclo e sai
    python -m src.engine.reconciliacao --loop   permanece reconciliando
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

from ..db import queries
from ..db.connection import conectar
from .confidence import load_config
from .config import get_settings
from .knowledge_base import load
from .service import ingerir
from .zabbix_client import ZabbixClient, ZabbixError

ESTADOS_ABERTOS = ("pendente", "executando")


@dataclass(frozen=True, slots=True)
class Reconciliacao:
    recuperados: int = 0
    ja_conhecidos: int = 0
    encerrados: int = 0

    def __str__(self) -> str:
        return (f"{self.recuperados} recuperado(s), {self.ja_conhecidos} já conhecido(s), "
                f"{self.encerrados} encerrado(s) na origem")


def reconciliar(conn, cliente: ZabbixClient, kb, config: dict | None = None) -> Reconciliacao:
    """Compara os problemas abertos no Zabbix com os incidentes pendentes no banco.

    Ingere o que faltou e encerra o que já não é problema lá.
    """
    cfg = config or load_config()
    alertas = cliente.alertas_abertos()
    abertos_no_zabbix = {a.id_evento for a in alertas if a.id_evento}

    recuperados = conhecidos = 0
    for alerta in alertas:
        resultado = ingerir(conn, alerta, kb, cfg)
        if resultado.duplicado:
            conhecidos += 1
        else:
            recuperados += 1

    encerrados = 0
    for pendente in queries.incidentes_abertos(conn):
        if pendente["id_evento"] and pendente["id_evento"] not in abertos_no_zabbix:
            queries.encerrar_por_origem(conn, pendente["id"])
            encerrados += 1
    conn.commit()

    return Reconciliacao(recuperados, conhecidos, encerrados)


def cliente_do_ambiente() -> ZabbixClient:
    s = get_settings()
    if not s.zabbix_url:
        raise ZabbixError("ZABBIX_URL não configurada")
    return ZabbixClient(url=s.zabbix_url, usuario=s.zabbix_user,
                        senha=s.zabbix_password, token=s.zabbix_token)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="polaris-reconciliar", description=__doc__.split("\n")[0])
    parser.add_argument("--loop", action="store_true", help="permanece reconciliando")
    parser.add_argument("--intervalo", type=int, default=None, help="segundos entre ciclos")
    args = parser.parse_args(argv)

    intervalo = args.intervalo or get_settings().polaris_polling_segundos
    kb, cfg = load(), load_config()

    try:
        cliente = cliente_do_ambiente()
    except ZabbixError as exc:
        print(f"reconciliação indisponível: {exc}", file=sys.stderr)
        return 2

    while True:
        try:
            with conectar() as conn:
                print(reconciliar(conn, cliente, kb, cfg))
        except ZabbixError as exc:
            print(f"ciclo falhou: {exc}", file=sys.stderr)
        if not args.loop:
            return 0
        time.sleep(max(intervalo, 5))


if __name__ == "__main__":
    raise SystemExit(main())
