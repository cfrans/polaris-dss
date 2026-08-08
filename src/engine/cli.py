"""Execução do motor pela linha de comando, sem Zabbix, sem banco e sem interface.

    python -m src.engine.cli src/tests/fixtures/disk_full.json
    python -m src.engine.cli src/tests/fixtures/cpu_high.json --json
    cat alerta.json | python -m src.engine.cli -
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .confidence import load_config
from .engine import analisar
from .history import Historico, HistoricoRegra, Recorrencia
from .knowledge_base import KnowledgeBaseError, load
from .models import Alert, Banda

_SIMBOLO = {Banda.ALTA: "ALTA", Banda.MEDIA: "MEDIA", Banda.BAIXA: "BAIXA"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="polaris-engine",
        description="Aplica a base de conhecimento a um alerta e imprime a sugestão explicada.",
    )
    parser.add_argument("alerta", help="arquivo JSON com o alerta, ou '-' para ler da entrada padrão")
    parser.add_argument("--rules", type=Path, default=None, help="caminho alternativo do rules.json")
    parser.add_argument("--json", action="store_true", help="imprime o trace completo em JSON")
    parser.add_argument(
        "--historico",
        nargs=3,
        metavar=("N", "SUCESSOS", "K"),
        type=int,
        help="simula histórico de auditoria para exercitar os fatores F3 e F4",
    )
    args = parser.parse_args(argv)

    try:
        kb = load(args.rules)
    except KnowledgeBaseError as exc:
        print(f"erro na base de conhecimento: {exc}", file=sys.stderr)
        return 2

    bruto = sys.stdin.read() if args.alerta == "-" else Path(args.alerta).read_text(encoding="utf-8")
    alert = Alert.from_dict(json.loads(bruto))

    historico = None
    if args.historico:
        n, sucessos, k = args.historico
        historico = Historico(HistoricoRegra(n=n, sucessos=sucessos), Recorrencia(k=k))

    sugestao = analisar(alert, kb, load_config(), historico)

    if sugestao is None:
        print(f"Nenhuma regra compatível com tipo_alerta='{alert.tipo_alerta}'.")
        print("O sistema não possui heurística formalizada para este incidente.")
        return 1

    if args.json:
        print(json.dumps(sugestao.trace.to_dict(), indent=2, ensure_ascii=False))
        return 0

    _imprimir(sugestao, kb.versao_kb)
    return 0


def _imprimir(sugestao, versao_kb: str) -> None:
    t = sugestao.trace
    largura = 78
    print("=" * largura)
    print(f"  {sugestao.rule.id} — {sugestao.rule.nome}")
    print(f"  host: {sugestao.alert.hostname}    base de conhecimento: v{versao_kb}")
    print("=" * largura)
    print()
    print(f"CONFIANÇA: {t.confianca_final:.0%}  [{_SIMBOLO[t.banda]}]   (base da regra: "
          f"{t.confianca_base:.0%})")
    print()

    print("DIAGNÓSTICO")
    for linha in _quebrar(sugestao.rule.diagnostico, largura - 2):
        print(f"  {linha}")
    print()

    print("EVIDÊNCIAS")
    m, tx = t.metrica, t.texto
    if m.aplicavel:
        marca = "confirma" if m.cruzou else "não confirma"
        print(f"  [{marca}] {m.chave}: {m.valor} {m.operador} {m.limiar}")
    else:
        print("  [n/a] métrica não avaliável para este alerta")
    if tx.aplicavel:
        marca = "confirma" if tx.casou else "não confirma"
        trecho = f' -> "{tx.trecho}"' if tx.trecho else ""
        print(f"  [{marca}] padrão textual{trecho}")
    else:
        print("  [n/a] regra sem condição textual")
    print()

    print("FATORES APLICADOS À CONFIANÇA")
    for fator in t.fatores:
        sinal = "  " if fator.valor == 1.0 else "->"
        print(f"  {sinal} {fator.id} x{fator.valor:.2f}  {fator.motivo}")
    print()

    print("AÇÃO SUGERIDA")
    print(f"  comando:  {sugestao.comando}")
    print(f"  rollback: {sugestao.rollback}")
    print(f"  timeout:  {sugestao.rule.remediacao.timeout_segundos}s"
          f"{'   (DESTRUTIVA)' if sugestao.rule.remediacao.destrutiva else ''}")
    print()

    if t.regras_candidatas_descartadas:
        print("OUTRAS REGRAS COMPATÍVEIS")
        for cand in t.regras_candidatas_descartadas:
            print(f"  {cand['regra']} — {cand['nome_regra']} ({cand['confianca']:.0%})")
        print()

    print("-" * largura)
    print("  Nenhuma ação foi executada. A remediação depende de aprovação humana registrada.")
    print("-" * largura)


def _quebrar(texto: str, largura: int) -> list[str]:
    palavras, linhas, atual = texto.split(), [], ""
    for palavra in palavras:
        if len(atual) + len(palavra) + 1 > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = f"{atual} {palavra}".strip()
    if atual:
        linhas.append(atual)
    return linhas


if __name__ == "__main__":
    raise SystemExit(main())
