"""Executa um ciclo completo de incidente contra o banco, com executor simulado.

Serve para verificar a persistência ponta a ponta antes de existirem interface, Zabbix e máquina
alvo: ingestão, exibição, decisão humana, execução e conclusão, com os cinco marcos temporais.

    python -m src.db.ciclo                          usa a fixture de serviço parado
    python -m src.db.ciclo --alerta <arquivo.json>
    python -m src.db.ciclo --rejeitar               exercita o caminho de rejeição
    python -m src.db.ciclo --sem-aprovacao          prova que a execução é recusada
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..engine.confidence import load_config
from ..engine.knowledge_base import load
from ..engine.models import Alert
from ..engine.service import ExecucaoNaoAutorizadaError, ExecutorSimulado, decidir, executar, exibir, ingerir
from . import queries
from .connection import conectar

FIXTURE_PADRAO = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "service_down.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="polaris-ciclo",
        description="Roda um ciclo completo de incidente contra o banco, sem executar remediação.",
    )
    parser.add_argument("--alerta", type=Path, default=FIXTURE_PADRAO)
    parser.add_argument("--operador", default="caio")
    parser.add_argument("--rejeitar", action="store_true", help="rejeita em vez de aprovar")
    parser.add_argument(
        "--sem-aprovacao",
        action="store_true",
        help="tenta executar sem registrar decisão, para verificar a recusa",
    )
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args(argv)

    kb = load()
    cfg = load_config()
    alerta = Alert.from_dict(json.loads(args.alerta.read_text(encoding="utf-8")))

    with conectar(args.dsn) as conn:
        print(f"alerta: {alerta.tipo_alerta} em {alerta.hostname}\n")

        ingestao = ingerir(conn, alerta, kb, cfg)
        if ingestao.sem_regra:
            print(f"  incidente {ingestao.incidente_id}: nenhuma regra compatível (no_match)")
            return 0
        if ingestao.duplicado:
            print(f"  incidente {ingestao.incidente_id}: evento já ingerido, nada duplicado")
            return 0

        s = ingestao.sugestao
        print(f"  t2 ingestão   incidente {ingestao.incidente_id} · regra {s.rule.id} · "
              f"confiança {s.confianca:.0%} [{s.banda.value}]")

        exibir(conn, ingestao.incidente_id)
        print("  t3 exibição   registrada")

        if args.sem_aprovacao:
            print("\n  tentando executar sem aprovação registrada ...")
            try:
                executar(conn, ingestao.incidente_id, ExecutorSimulado())
            except ExecucaoNaoAutorizadaError as exc:
                print(f"  RECUSADO: {exc}")
                return 0
            print("  FALHA GRAVE: a execução não foi recusada", file=sys.stderr)
            return 1

        aprovado = not args.rejeitar
        decidir(conn, ingestao.incidente_id, aprovado, args.operador,
                motivo=None if aprovado else "rejeitado na demonstração")
        print(f"  t4 decisão    {'aprovado' if aprovado else 'rejeitado'} por {args.operador}")

        if aprovado:
            resultado = executar(conn, ingestao.incidente_id, ExecutorSimulado())
            print(f"  t5 conclusão  {resultado.status} (exit {resultado.exit_code})")

        registro = queries.obter_incidente(conn, ingestao.incidente_id)

    print("\nregistro de auditoria")
    for campo in ("status_execucao", "decisao_humana", "operador", "confianca_calculada",
                  "banda_confianca", "comando_executado", "ts_deteccao", "ts_criacao",
                  "ts_exibicao", "ts_aprovacao", "ts_conclusao", "mttr_calculado"):
        print(f"  {campo:<20} {registro[campo]}")

    fatores = registro["explicabilidade"]["fatores"]
    print("\nfatores de confiança gravados no trace")
    for f in fatores:
        print(f"  {f['id']} x{f['valor']:.2f}  {f['motivo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
