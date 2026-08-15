"""Tipos do domínio do motor de inferência.

Os nomes de campo da base de conhecimento e da auditoria são mantidos em português por
corresponderem ao Quadro 1 da monografia. O restante do código é em inglês.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from string import Formatter
from typing import Any

VERSAO_MOTOR = "0.2.0"

SEVERIDADES = ("baixa", "media", "alta", "critica")

# Valores de parâmetro entram em linha de comando. A allowlist admite nome de serviço/processo e
# caminho absoluto, e exclui todo metacaractere de shell: espaço, ; | & $ ` ( ) < > aspas e quebra
# de linha. Travessia de diretório é barrada à parte, porque '..' passa pelo conjunto de caracteres.
PARAM_PERMITIDO = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")


class Banda(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"


class ParametroInvalidoError(ValueError):
    """Placeholder sem parâmetro correspondente, ou valor fora do formato permitido."""


@dataclass(frozen=True, slots=True)
class Alert:
    """Evento normalizado. É o que o motor consome, venha do webhook, do polling ou de fixture."""

    tipo_alerta: str
    hostname: str
    texto: str = ""
    valor: float | None = None
    metrica: str | None = None
    severidade: str | None = None
    id_evento: str | None = None
    ts_deteccao: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Alert:
        ts = data.get("ts_deteccao")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        valor = data.get("valor")
        return cls(
            tipo_alerta=data["tipo_alerta"],
            hostname=data["hostname"],
            texto=data.get("texto", "") or "",
            valor=float(valor) if valor is not None else None,
            metrica=data.get("metrica"),
            severidade=data.get("severidade"),
            id_evento=data.get("id_evento"),
            ts_deteccao=ts,
        )


@dataclass(frozen=True, slots=True)
class Condicao:
    tipo_alerta: str
    regex_log: str | None = None
    limiar_uso_pct: float | None = None
    metrica: str | None = None
    operador: str = ">="
    parametros: dict[str, str] = field(default_factory=dict)
    processos_alvo_permitidos: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Remediacao:
    comando: str
    rollback: str
    timeout_segundos: int
    script: str | None = None
    verificador: str | None = None
    requer_sudo: bool = True
    destrutiva: bool = False


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    nome: str
    condicao: Condicao
    diagnostico: str
    remediacao: Remediacao
    confianca_base: float
    habilitada: bool = True
    severidade_minima: str | None = None
    referencia: str | None = None
    # Posição no rules.json. Último critério de desempate, garante ordenação determinística.
    ordem: int = 0

    def render(self, template: str) -> str:
        """Substitui placeholders usando apenas `condicao.parametros`.

        Nada vindo do alerta entra aqui: os parâmetros vêm do rules.json versionado, revisado por
        um humano, e ainda assim passam por allowlist de caracteres antes da substituição.
        """
        valores: dict[str, str] = {}
        for _, campo, _, _ in Formatter().parse(template):
            if campo is None:
                continue
            if campo not in self.condicao.parametros:
                raise ParametroInvalidoError(
                    f"regra {self.id}: placeholder '{{{campo}}}' sem parâmetro correspondente "
                    f"em condicao.parametros"
                )
            valor = self.condicao.parametros[campo]
            if not PARAM_PERMITIDO.match(valor):
                raise ParametroInvalidoError(
                    f"regra {self.id}: valor '{valor}' do parâmetro '{campo}' contém caractere "
                    f"não permitido"
                )
            if ".." in valor:
                raise ParametroInvalidoError(
                    f"regra {self.id}: valor '{valor}' do parâmetro '{campo}' contém travessia "
                    f"de diretório"
                )
            valores[campo] = valor
        return template.format(**valores)


@dataclass(frozen=True, slots=True)
class EvidenciaMetrica:
    aplicavel: bool
    cruzou: bool
    chave: str | None = None
    valor: float | None = None
    limiar: float | None = None
    operador: str = ">="

    def to_dict(self) -> dict[str, Any]:
        return {
            "chave": self.chave,
            "valor": self.valor,
            "limiar": self.limiar,
            "operador": self.operador,
            "aplicavel": self.aplicavel,
            "cruzou": self.cruzou,
        }


@dataclass(frozen=True, slots=True)
class EvidenciaTexto:
    aplicavel: bool
    casou: bool
    regex: str | None = None
    trecho: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "regex": self.regex,
            "aplicavel": self.aplicavel,
            "casou": self.casou,
            "trecho": self.trecho,
        }


@dataclass(frozen=True, slots=True)
class Fator:
    id: str
    nome: str
    valor: float
    motivo: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "nome": self.nome, "valor": self.valor, "motivo": self.motivo}


@dataclass(frozen=True, slots=True)
class ConfidenceTrace:
    """Registro de explicabilidade. Vai inteiro para `audit_log.explicabilidade` (JSONB).

    É o que torna qualquer decisão passada reproduzível: guarda as evidências observadas, cada
    fator aplicado com o motivo, e as versões da base e do motor vigentes no momento.
    """

    regra: str
    nome_regra: str
    confianca_base: float
    confianca_final: float
    banda: Banda
    metrica: EvidenciaMetrica
    texto: EvidenciaTexto
    fatores: tuple[Fator, ...]
    versao_kb: str
    versao_motor: str = VERSAO_MOTOR
    regras_candidatas_descartadas: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "regra": self.regra,
            "nome_regra": self.nome_regra,
            "confianca_base": self.confianca_base,
            "confianca_final": self.confianca_final,
            "banda": self.banda.value,
            "evidencias": {"metrica": self.metrica.to_dict(), "texto": self.texto.to_dict()},
            "fatores": [f.to_dict() for f in self.fatores],
            "regras_candidatas_descartadas": list(self.regras_candidatas_descartadas),
            "versao_kb": self.versao_kb,
            "versao_motor": self.versao_motor,
        }


@dataclass(frozen=True, slots=True)
class Match:
    """Regra que casou com o alerta, com as evidências que a dispararam."""

    rule: Rule
    metrica: EvidenciaMetrica
    texto: EvidenciaTexto


@dataclass(frozen=True, slots=True)
class Suggestion:
    """Sugestão apresentada ao operador. O motor para aqui: quem executa é a decisão humana."""

    alert: Alert
    rule: Rule
    comando: str
    rollback: str
    trace: ConfidenceTrace
    verificador: str | None = None

    @property
    def confianca(self) -> float:
        return self.trace.confianca_final

    @property
    def banda(self) -> Banda:
        return self.trace.banda
