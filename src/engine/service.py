"""Orquestração do ciclo de vida de um incidente.

Impõe a invariante do sistema, e não a interface nem o banco:

    nenhuma remediação é executada sem um registro de aprovação humana já persistido.

A ordem em `decidir` é significativa: grava, conclui a transação e só então libera a execução. Se o
processo for interrompido entre a gravação e a execução, o banco mostra aprovação sem execução —
estado recuperável e auditável.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..db import queries
from .confidence import load_config
from .config import get_settings
from .engine import analisar
from .knowledge_base import KnowledgeBase
from .models import Alert, Suggestion


class ExecucaoNaoAutorizadaError(RuntimeError):
    """Tentativa de executar remediação sem aprovação humana registrada."""


@dataclass(frozen=True, slots=True)
class ResultadoExecucao:
    status: str
    exit_code: int | None = None
    saida: str | None = None
    erro: str | None = None
    saudavel: bool = False


class Executor(Protocol):
    """Contrato do executor de remediação.

    `verificador` é o comando que confirma o restabelecimento; sem ele, o incidente não pode ser
    fechado como sucesso.
    """

    def __call__(self, comando: str, verificador: str | None = None,
                 timeout_segundos: int = 60) -> ResultadoExecucao: ...


@dataclass(frozen=True, slots=True)
class ExecutorSimulado:
    """Registra o que executaria, sem tocar em nada.

    Permite exercitar o ciclo completo — inclusive a recusa de execução não autorizada — antes de
    existir uma máquina alvo.
    """

    saudavel: bool = True

    def __call__(self, comando: str, verificador: str | None = None,
                 timeout_segundos: int = 60) -> ResultadoExecucao:
        return ResultadoExecucao(
            status="sucesso" if self.saudavel else "falha",
            exit_code=0 if self.saudavel else 1,
            saida=f"[simulado] comando não executado: {comando}",
            saudavel=self.saudavel,
        )


def executor_padrao() -> Executor:
    """Devolve o executor real quando há host alvo configurado, e o simulado caso contrário.

    A ausência de `TARGET_SSH_HOST` é o que mantém o sistema inofensivo em ambiente de
    desenvolvimento: sem host configurado, aprovar um incidente registra a decisão e não toca em
    máquina nenhuma.
    """
    s = get_settings()
    if not (s.target_ssh_host and s.target_ssh_key_path):
        return ExecutorSimulado()

    from .remediation import ExecutorRemoto, runner_ssh

    return ExecutorRemoto(
        runner=runner_ssh(s.target_ssh_host, s.target_ssh_user, s.target_ssh_key_path)
    )


@dataclass(frozen=True, slots=True)
class Ingestao:
    incidente_id: int
    sugestao: Suggestion | None
    duplicado: bool = False
    sem_regra: bool = False


def ingerir(
    conn,
    alert: Alert,
    kb: KnowledgeBase,
    config: dict | None = None,
    usar_historico: bool | None = None,
    experiment_run_id: int | None = None,
) -> Ingestao:
    """Analisa o alerta e persiste o incidente como pendente. Nada é executado aqui."""
    cfg = config or load_config()

    if usar_historico is None:
        usar_historico = get_settings().polaris_confidence_history

    # O histórico depende da regra, que só se conhece depois de analisar. Primeira passada sem
    # histórico define a regra candidata; a segunda recalcula a confiança já com os fatores F3 e F4.
    sugestao = analisar(alert, kb, cfg)
    if sugestao is not None and usar_historico:
        historico = queries.carregar_historico(conn, alert.hostname, sugestao.rule.id, cfg)
        sugestao = analisar(alert, kb, cfg, historico)

    persistido = queries.criar_incidente(conn, alert, sugestao, experiment_run_id)
    conn.commit()
    return Ingestao(
        incidente_id=persistido.incidente_id,
        sugestao=sugestao,
        duplicado=persistido.duplicado,
        sem_regra=persistido.sem_regra,
    )


def exibir(conn, incidente_id: int) -> bool:
    """Registra t3, quando a interface efetivamente renderizou o incidente ao operador.

    Sem este marco não existe tempo de decisão humana, e sem ele não há como decompor o MTTR.
    """
    marcado = queries.marcar_exibicao(conn, incidente_id)
    conn.commit()
    return marcado


def decidir(
    conn, incidente_id: int, aprovado: bool, operador: str, motivo: str | None = None
) -> bool:
    """Grava a decisão humana e **conclui a transação** antes de qualquer execução."""
    registrado = queries.registrar_decisao(conn, incidente_id, aprovado, operador, motivo)
    conn.commit()
    return registrado


def executar(conn, incidente_id: int, executor: Executor,
             timeout_segundos: int = 60) -> ResultadoExecucao:
    """Executa a remediação, mas só depois de reler a aprovação já persistida.

    A releitura é deliberada: o executor não confia no que quem chamou afirma ter feito, e sim no
    que está gravado. É este ponto que torna a invariante uma checagem, e não uma promessa.
    """
    incidente = queries.obter_incidente(conn, incidente_id)
    if incidente is None:
        raise ExecucaoNaoAutorizadaError(f"incidente {incidente_id} não existe")
    if incidente["decisao_humana"] is not True or incidente["ts_aprovacao"] is None:
        raise ExecucaoNaoAutorizadaError(
            f"incidente {incidente_id} não possui aprovação humana registrada "
            f"(decisao_humana={incidente['decisao_humana']}, "
            f"ts_aprovacao={incidente['ts_aprovacao']})"
        )
    if incidente["status_execucao"] != "executando":
        raise ExecucaoNaoAutorizadaError(
            f"incidente {incidente_id} está em '{incidente['status_execucao']}', "
            f"não em 'executando'"
        )

    resultado = executor(
        incidente["comando_executado"],
        verificador=incidente.get("comando_verificacao"),
        timeout_segundos=timeout_segundos,
    )

    # t5 só é gravado com a saúde confirmada: código de retorno zero não é prova de
    # restabelecimento, e fechar por ele superestimaria a taxa de acerto das heurísticas.
    queries.registrar_execucao(
        conn,
        incidente_id,
        status=resultado.status,
        exit_code=resultado.exit_code,
        saida=resultado.saida,
        erro=resultado.erro,
        concluir=resultado.saudavel,
    )
    conn.commit()
    return resultado
