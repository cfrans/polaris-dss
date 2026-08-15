"""Execução remota da remediação no host alvo.

A lógica de decisão fica em `ExecutorRemoto`, que recebe um `Runner` — qualquer coisa capaz de
executar um comando e devolver código de saída, saída padrão e erro. O transporte SSH é um adaptador
fino sobre paramiko. A separação existe para que o comportamento seja testável sem máquina remota.

Duas garantias sustentadas aqui:

- O comando vem da base de conhecimento, com os parâmetros já validados. Este módulo apenas resolve
  o caminho do script e prefixa `sudo`; não compõe, não interpola e não corrige comando.
- Código de saída zero não fecha o incidente. Só o verificador do cenário confirma restabelecimento,
  porque um serviço pode reiniciar com sucesso e cair em seguida.
"""

from __future__ import annotations

import shlex
import time
from dataclasses import dataclass
from typing import Protocol

from .service import ResultadoExecucao

DIRETORIO_SCRIPTS = "/opt/polaris/bin"


class Runner(Protocol):
    """Executa um comando no host alvo e devolve (código de saída, saída, erro)."""

    def __call__(self, comando: str, timeout: int) -> tuple[int, str, str]: ...


class RemediacaoIndisponivelError(RuntimeError):
    """Host alvo não configurado ou inacessível."""


def montar_comando(comando: str, diretorio_scripts: str = DIRETORIO_SCRIPTS,
                   com_sudo: bool = True) -> str:
    """Resolve o caminho do script e prefixa `sudo`.

    Comando cujo primeiro termo termina em `.sh` é tratado como script publicado no diretório
    controlado; qualquer outro é deixado como está, para que o `sudo` resolva o binário pelo PATH.
    A forma final precisa casar exatamente com a entrada correspondente em `/etc/sudoers.d/polaris`.
    """
    partes = shlex.split(comando)
    if not partes:
        raise ValueError("comando vazio")
    if partes[0].endswith(".sh") and "/" not in partes[0]:
        partes[0] = f"{diretorio_scripts.rstrip('/')}/{partes[0]}"
    montado = " ".join(shlex.quote(p) if " " in p else p for p in partes)
    return f"sudo {montado}" if com_sudo else montado


@dataclass(frozen=True, slots=True)
class ExecutorRemoto:
    """Executa a remediação e confirma o restabelecimento pelo verificador do cenário.

    A confirmação exige acertos consecutivos: um serviço que oscila pode responder saudável num
    instante e cair no seguinte, e fechar o incidente nesse intervalo registraria acerto onde não
    houve.
    """

    runner: Runner
    diretorio_scripts: str = DIRETORIO_SCRIPTS
    tentativas_verificacao: int = 5
    confirmacoes_consecutivas: int = 2
    intervalo_verificacao: float = 2.0

    def __call__(self, comando: str, verificador: str | None = None,
                 timeout_segundos: int = 60) -> ResultadoExecucao:
        alvo = montar_comando(comando, self.diretorio_scripts, com_sudo=True)

        try:
            codigo, saida, erro = self.runner(alvo, timeout=timeout_segundos)
        except TimeoutError:
            return ResultadoExecucao(
                status="timeout", exit_code=None, saida=None,
                erro=f"o comando excedeu {timeout_segundos}s e foi interrompido",
                saudavel=False,
            )
        except Exception as exc:
            return ResultadoExecucao(status="falha", exit_code=None, saida=None,
                                     erro=f"falha de execução remota: {exc}", saudavel=False)

        # Exit code 2 é a recusa deliberada dos scripts: alvo fora da allowlist, caminho não
        # previsto. Não é falha do sistema, e sim o script se recusando a agir sem respaldo.
        if codigo == 2:
            return ResultadoExecucao(status="falha", exit_code=codigo, saida=saida,
                                     erro=(erro or "").strip() or "ação recusada pelo script",
                                     saudavel=False)

        saudavel, detalhe = self._confirmar(verificador)
        status = "sucesso" if saudavel else "falha"
        return ResultadoExecucao(
            status=status,
            exit_code=codigo,
            saida=(saida or "").strip() or None,
            erro=("\n".join(p for p in ((erro or "").strip(), detalhe) if p)) or None,
            saudavel=saudavel,
        )

    def _confirmar(self, verificador: str | None) -> tuple[bool, str]:
        if not verificador:
            return False, ("sem verificador declarado para a regra: o restabelecimento não pôde "
                           "ser confirmado, e o incidente permanece sem conclusão")

        # O verificador consulta estado e não altera nada — roda sem privilégio elevado.
        alvo = montar_comando(verificador, self.diretorio_scripts, com_sudo=False)
        consecutivos = 0
        for tentativa in range(self.tentativas_verificacao):
            if tentativa:
                time.sleep(self.intervalo_verificacao)
            try:
                codigo, _, _ = self.runner(alvo, timeout=30)
            except Exception as exc:
                return False, f"o verificador não pôde ser executado: {exc}"
            consecutivos = consecutivos + 1 if codigo == 0 else 0
            if consecutivos >= self.confirmacoes_consecutivas:
                return True, ""
        return False, (f"o verificador não confirmou o restabelecimento em "
                       f"{self.tentativas_verificacao} tentativas")


def runner_ssh(host: str, usuario: str, caminho_chave: str, porta: int = 22) -> Runner:
    """Adaptador sobre paramiko. Abre uma conexão por comando: o volume é baixo e a alternativa
    exigiria gerenciar reconexão de sessão longa sem ganho perceptível."""
    import paramiko

    def executar(comando: str, timeout: int) -> tuple[int, str, str]:
        cliente = paramiko.SSHClient()
        cliente.set_missing_host_key_policy(paramiko.RejectPolicy())
        cliente.load_system_host_keys()
        try:
            cliente.connect(hostname=host, port=porta, username=usuario,
                            key_filename=caminho_chave, timeout=10, auth_timeout=10)
            _, stdout, stderr = cliente.exec_command(comando, timeout=timeout)
            saida = stdout.read().decode("utf-8", "replace")
            erro = stderr.read().decode("utf-8", "replace")
            return stdout.channel.recv_exit_status(), saida, erro
        finally:
            cliente.close()

    return executar
