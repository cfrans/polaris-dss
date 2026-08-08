"""Carga e validação da base de conhecimento.

A validação falha ruidosamente e derruba a inicialização: base inválida silenciosamente ignorada é
o pior modo de falha de um sistema especialista, porque o operador confiaria numa cobertura que não
existe.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from .models import Condicao, Remediacao, Rule

ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT / "src" / "knowledge_base" / "rules.json"
SCHEMA_PATH = ROOT / "src" / "knowledge_base" / "schema.json"


class KnowledgeBaseError(Exception):
    """Base de conhecimento ausente, malformada ou semanticamente inválida."""


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    versao_kb: str
    regras: tuple[Rule, ...]

    def por_id(self, rule_id: str) -> Rule | None:
        return next((r for r in self.regras if r.id == rule_id), None)

    @property
    def habilitadas(self) -> tuple[Rule, ...]:
        return tuple(r for r in self.regras if r.habilitada)


def load(rules_path: Path | None = None, schema_path: Path | None = None) -> KnowledgeBase:
    rules_path = Path(rules_path) if rules_path else RULES_PATH
    schema_path = Path(schema_path) if schema_path else SCHEMA_PATH

    raw = _read_json(rules_path, "base de conhecimento")
    schema = _read_json(schema_path, "JSON Schema")

    try:
        jsonschema.validate(instance=raw, schema=schema)
    except jsonschema.ValidationError as exc:
        caminho = "/".join(str(p) for p in exc.absolute_path) or "(raiz)"
        raise KnowledgeBaseError(
            f"{rules_path.name} inválido em '{caminho}': {exc.message}"
        ) from exc

    regras = tuple(_build_rule(item, ordem) for ordem, item in enumerate(raw["regras"]))
    _check_ids_unicos(regras)
    for regra in regras:
        _check_regex(regra)
        _check_placeholders(regra)

    return KnowledgeBase(versao_kb=raw["versao_kb"], regras=regras)


def _read_json(path: Path, descricao: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KnowledgeBaseError(f"{descricao} não encontrada em {path}") from exc
    except json.JSONDecodeError as exc:
        raise KnowledgeBaseError(f"{descricao} em {path} não é JSON válido: {exc}") from exc


def _build_rule(item: dict, ordem: int) -> Rule:
    cond = item["condicao"]
    rem = item["remediacao"]
    return Rule(
        id=item["id"],
        nome=item["nome"],
        condicao=Condicao(
            tipo_alerta=cond["tipo_alerta"],
            regex_log=cond.get("regex_log"),
            limiar_uso_pct=cond.get("limiar_uso_pct"),
            metrica=cond.get("metrica"),
            operador=cond.get("operador", ">="),
            parametros=dict(cond.get("parametros", {})),
            processos_alvo_permitidos=tuple(cond.get("processos_alvo_permitidos", ())),
        ),
        diagnostico=item["diagnostico"],
        remediacao=Remediacao(
            comando=rem["comando"],
            rollback=rem["rollback"],
            timeout_segundos=rem["timeout_segundos"],
            script=rem.get("script"),
            verificador=rem.get("verificador"),
            requer_sudo=rem.get("requer_sudo", True),
            destrutiva=rem.get("destrutiva", False),
        ),
        confianca_base=item["confianca_base"],
        habilitada=item.get("habilitada", True),
        severidade_minima=item.get("severidade_minima"),
        referencia=item.get("referencia"),
        ordem=ordem,
    )


def _check_ids_unicos(regras: tuple[Rule, ...]) -> None:
    vistos: set[str] = set()
    for regra in regras:
        if regra.id in vistos:
            raise KnowledgeBaseError(f"id de regra duplicado: {regra.id}")
        vistos.add(regra.id)


def _check_regex(regra: Rule) -> None:
    if regra.condicao.regex_log is None:
        return
    try:
        re.compile(regra.condicao.regex_log)
    except re.error as exc:
        raise KnowledgeBaseError(
            f"regra {regra.id}: regex_log inválido ({exc})"
        ) from exc


def _check_placeholders(regra: Rule) -> None:
    """Falha na carga, não na execução: placeholder órfão só apareceria na hora de remediar."""
    alvos = [regra.remediacao.comando, regra.remediacao.rollback]
    if regra.remediacao.verificador:
        alvos.append(regra.remediacao.verificador)
    for template in alvos:
        try:
            regra.render(template)
        except ValueError as exc:
            raise KnowledgeBaseError(str(exc)) from exc
