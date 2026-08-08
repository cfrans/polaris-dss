"""Contratos de entrada e saída da API.

Os nomes de campo acompanham o vocabulário do domínio (português), coerentes com a base de
conhecimento e com as colunas de auditoria.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Erro(BaseModel):
    erro: str
    mensagem: str
    detalhes: dict[str, Any] = Field(default_factory=dict)


class IncidenteResumo(BaseModel):
    id: int
    id_evento: str | None = None
    hostname: str | None = None
    severidade: str | None = None
    regra: str | None = None
    nome_regra: str | None = None
    confianca: float | None = None
    banda: str | None = None
    status: str
    ts_criacao: datetime


class ListaIncidentes(BaseModel):
    total: int
    itens: list[IncidenteResumo]


class Evidencias(BaseModel):
    metrica: dict[str, Any]
    texto: dict[str, Any]


class IncidenteDetalhe(BaseModel):
    id: int
    id_evento: str | None = None
    hostname: str | None = None
    severidade: str | None = None
    status: str
    regra: str | None = None
    nome_regra: str | None = None
    diagnostico: str | None = None
    comando: str | None = None
    rollback: str | None = None
    destrutiva: bool = False
    timeout_segundos: int | None = None
    confianca: float | None = None
    banda: str | None = None
    evidencias: Evidencias | None = None
    fatores: list[dict[str, Any]] = Field(default_factory=list)
    candidatas_descartadas: list[dict[str, Any]] = Field(default_factory=list)
    versao_kb: str | None = None
    versao_motor: str | None = None
    decisao_humana: bool | None = None
    operador: str | None = None
    motivo_rejeicao: str | None = None
    exit_code: int | None = None
    output: str | None = None
    erro_execucao: str | None = None
    ts_deteccao: datetime | None = None
    ts_criacao: datetime
    ts_exibicao: datetime | None = None
    ts_aprovacao: datetime | None = None
    ts_conclusao: datetime | None = None


class DecisaoRequest(BaseModel):
    aprovado: bool
    operador: str = Field(min_length=1, max_length=64)
    motivo: str | None = Field(default=None, max_length=1000)


class DecisaoResponse(BaseModel):
    status: str
    incidente_id: int


class ResultadoResponse(BaseModel):
    incidente_id: int
    status: str
    exit_code: int | None = None
    output: str | None = None
    erro: str | None = None
    ts_conclusao: datetime | None = None
    mttr_segundos: float | None = None


class AlertaSimulado(BaseModel):
    """Entrada do endpoint de simulação, no formato interno já normalizado."""

    tipo_alerta: str
    hostname: str
    texto: str = ""
    valor: float | None = None
    metrica: str | None = None
    severidade: Literal["baixa", "media", "alta", "critica"] | None = None
    id_evento: str | None = None


class IngestaoResponse(BaseModel):
    status: Literal["created", "duplicate", "no_match"]
    incidente_id: int
    regra: str | None = None
    confianca: float | None = None
    banda: str | None = None
    motivo: str | None = None


class Saude(BaseModel):
    status: str
    db: str
    kb: str
    versao: str
    versao_kb: str | None = None
    debug: bool = False
