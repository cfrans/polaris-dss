"""Estatísticas de auditoria consumidas pelos fatores F3 (histórico) e F4 (recorrência).

O cálculo de confiança recebe estes valores já resolvidos e nunca consulta o banco por conta
própria — o que mantém a fórmula testável com valores fabricados e o motor utilizável sem
infraestrutura.

O provedor com acesso ao PostgreSQL entra em v0.3.0, junto de `db/queries.py`, e preencherá estes
mesmos tipos a partir de `audit_log`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HistoricoRegra:
    """Execuções aprovadas e concluídas desta regra na janela configurada."""

    n: int
    sucessos: int

    @property
    def taxa_sucesso(self) -> float:
        return self.sucessos / self.n if self.n else 0.0


@dataclass(frozen=True, slots=True)
class Recorrencia:
    """Quantas vezes esta combinação host+regra já foi remediada com sucesso na janela recente.

    k >= 1 indica que a remediação anterior não sustentou a correção, o que sugere causa-raiz
    distinta da diagnosticada.
    """

    k: int


@dataclass(frozen=True, slots=True)
class Historico:
    regra: HistoricoRegra | None = None
    recorrencia: Recorrencia | None = None


# Estado usado quando não há banco disponível ou quando os fatores dependentes de histórico estão
# desligados (POLARIS_CONFIDENCE_HISTORY=false, como na coleta oficial de dados).
SEM_HISTORICO = Historico()
