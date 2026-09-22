"""Execução remota de scripts padrão mantidos no servidor Polaris.

Os bytes aprovados são enviados pela entrada padrão do SSH. O alvo não precisa manter cópias dos
scripts; o verificador continua responsável por confirmar o restabelecimento.
"""

from __future__ import annotations

import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .script_catalog import ScriptCatalog
from .service import ResultadoExecucao

NATIVE_ACTIONS = {("systemctl", "restart", "nginx")}
SYSTEM_KNOWN_HOSTS = Path("/etc/ssh/ssh_known_hosts")


class Runner(Protocol):
    """Executa um comando no host alvo e envia bytes opcionais pela entrada padrão."""

    def __call__(self, command: str, timeout: int,
                 input_data: bytes | None = None) -> tuple[int, str, str]: ...


class RemediacaoIndisponivelError(RuntimeError):
    """Host alvo não configurado ou inacessível."""


def prepare_command(command: str, catalog: ScriptCatalog, timeout: int,
                    with_sudo: bool = True) -> tuple[str, bytes | None]:
    """Monta a linha remota e seleciona os bytes do script permitido."""
    parts = shlex.split(command)
    if not parts:
        raise ValueError("comando vazio")
    if timeout < 1:
        raise ValueError("timeout inválido")
    prefix = "sudo -n " if with_sudo else ""
    base = f"{prefix}/usr/bin/timeout -k 5s {timeout}s"
    if parts[0].endswith(".sh"):
        if "/" in parts[0]:
            raise ValueError("caminho de script não autorizado")
        script = catalog.get(parts[0])
        args = " ".join(shlex.quote(part) for part in parts[1:])
        return f"{base} /usr/bin/bash -s --" + (f" {args}" if args else ""), script.content
    if not with_sudo or tuple(parts) not in NATIVE_ACTIONS:
        raise ValueError(f"comando nativo não autorizado: {command}")
    return f"{base} /usr/bin/systemctl restart nginx", None


@dataclass(frozen=True, slots=True)
class ExecutorRemoto:
    """Executa a remediação e confirma o restabelecimento pelo verificador do cenário.

    A confirmação exige acertos consecutivos: um serviço que oscila pode responder saudável num
    instante e cair no seguinte, e fechar o incidente nesse intervalo registraria acerto onde não
    houve.
    """

    runner: Runner
    catalog: ScriptCatalog
    tentativas_verificacao: int = 5
    confirmacoes_consecutivas: int = 2
    intervalo_verificacao: float = 2.0

    def __call__(self, comando: str, verificador: str | None = None,
                 timeout_segundos: int = 60) -> ResultadoExecucao:
        try:
            target, input_data = prepare_command(comando, self.catalog, timeout_segundos)
        except ValueError as exc:
            return ResultadoExecucao(status="falha", erro=str(exc), saudavel=False)

        try:
            codigo, saida, erro = self.runner(target, timeout=timeout_segundos + 10,
                                              input_data=input_data)
        except TimeoutError:
            return ResultadoExecucao(
                status="timeout", exit_code=None, saida=None,
                erro=f"o comando excedeu {timeout_segundos}s",
                saudavel=False,
            )
        except Exception as exc:
            return ResultadoExecucao(status="falha", exit_code=None, saida=None,
                                     erro=f"falha de execução remota: {exc}", saudavel=False)

        if codigo == 124:
            return ResultadoExecucao(status="timeout", exit_code=codigo, saida=saida,
                                     erro=erro or f"o comando excedeu {timeout_segundos}s",
                                     saudavel=False)
        if codigo != 0:
            return ResultadoExecucao(status="falha", exit_code=codigo, saida=saida,
                                     erro=(erro or "").strip() or f"comando terminou com código {codigo}",
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
        try:
            target, input_data = prepare_command(verificador, self.catalog, 30, with_sudo=False)
        except ValueError as exc:
            return False, f"verificador não autorizado: {exc}"
        consecutivos = 0
        for tentativa in range(self.tentativas_verificacao):
            if tentativa:
                time.sleep(self.intervalo_verificacao)
            try:
                codigo, _, _ = self.runner(target, timeout=40, input_data=input_data)
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

    def executar(comando: str, timeout: int,
                input_data: bytes | None = None) -> tuple[int, str, str]:
        cliente = paramiko.SSHClient()
        cliente.set_missing_host_key_policy(paramiko.RejectPolicy())
        if SYSTEM_KNOWN_HOSTS.is_file():
            cliente.load_system_host_keys(str(SYSTEM_KNOWN_HOSTS))
        else:
            cliente.load_system_host_keys()
        try:
            cliente.connect(hostname=host, port=porta, username=usuario,
                            key_filename=caminho_chave, timeout=10, auth_timeout=10)
            stdin, stdout, stderr = cliente.exec_command(comando, timeout=timeout)
            if input_data is not None:
                stdin.write(input_data)
                stdin.flush()
            stdin.channel.shutdown_write()
            saida = stdout.read().decode("utf-8", "replace")
            erro = stderr.read().decode("utf-8", "replace")
            return stdout.channel.recv_exit_status(), saida, erro
        finally:
            cliente.close()

    return executar
