"""Executor de remediação.

Nenhum teste abre conexão SSH: o executor recebe um `Runner` dublê, que registra os comandos
recebidos e devolve os códigos de saída combinados. É o que permite exercitar as decisões — quando
fechar o incidente, quando recusar, quando insistir na verificação — sem host remoto.
"""

from __future__ import annotations

import pytest
import subprocess
import shutil

from src.engine.remediation import ExecutorRemoto, prepare_command
from src.engine.script_catalog import load_catalog


class RunnerDuble:
    """Devolve os códigos de saída na ordem combinada e guarda o que foi executado."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas: list[str] = []
        self.entradas: list[bytes | None] = []

    def __call__(self, comando, timeout, input_data=None):
        self.chamadas.append(comando)
        self.entradas.append(input_data)
        if not self.respostas:
            return 0, "", ""
        proxima = self.respostas.pop(0)
        if isinstance(proxima, Exception):
            raise proxima
        codigo = proxima if isinstance(proxima, int) else proxima[0]
        saida = "" if isinstance(proxima, int) else proxima[1]
        erro = "" if isinstance(proxima, int) else proxima[2]
        return codigo, saida, erro


def executor(respostas, **kwargs):
    runner = RunnerDuble(respostas)
    return ExecutorRemoto(runner=runner, catalog=load_catalog(),
                          intervalo_verificacao=0, **kwargs), runner


# ---------------------------------------------------------------------------
# Montagem do comando
# ---------------------------------------------------------------------------


def test_script_e_enviado_pela_entrada_padrao():
    command, content = prepare_command("disk_cleanup.sh /mnt/polaris_test", load_catalog(), 60)
    assert command == "sudo -n /usr/bin/timeout -k 5s 60s /usr/bin/bash -s -- /mnt/polaris_test"
    assert content == load_catalog().get("disk_cleanup.sh").content


def test_comando_nativo_fica_limitado_ao_nginx():
    command, content = prepare_command("systemctl restart nginx", load_catalog(), 120)
    assert command.endswith("/usr/bin/systemctl restart nginx")
    assert content is None


def test_verificador_roda_sem_privilegio_elevado():
    command, content = prepare_command("verify_service.sh nginx", load_catalog(), 30,
                                       with_sudo=False)
    assert command == "/usr/bin/timeout -k 5s 30s /usr/bin/bash -s -- nginx"
    assert content == load_catalog().get("verify_service.sh").content


def test_bytes_transmitidos_executam_sem_arquivo_no_alvo():
    command, content = prepare_command("disk_cleanup.sh /", load_catalog(), 30,
                                       with_sudo=False)
    # O macOS não fornece /usr/bin/timeout; este teste exercita a passagem por stdin ao bash.
    shell_command = command.removeprefix("/usr/bin/timeout -k 5s 30s ")
    shell_command = shell_command.replace("/usr/bin/bash", shutil.which("bash") or "bash", 1)
    result = subprocess.run(shell_command, shell=True, input=content, capture_output=True,
                            timeout=35)
    assert result.returncode == 2
    assert "ponto de montagem não permitido: /" in result.stderr.decode()


def test_ssh_carrega_host_validado_sem_aceitar_desconhecidos(monkeypatch, tmp_path):
    import paramiko
    import src.engine.remediation as remediation

    known_hosts = tmp_path / "known_hosts"
    keys = paramiko.HostKeys()
    keys.add("192.0.2.10", "ssh-rsa", paramiko.RSAKey.generate(1024))
    keys.save(str(known_hosts))
    monkeypatch.setattr(remediation, "SYSTEM_KNOWN_HOSTS", known_hosts)

    def check_connect(client, **kwargs):
        assert isinstance(client._policy, paramiko.RejectPolicy)
        assert client._system_host_keys.lookup("192.0.2.10") is not None
        raise OSError("conexão simulada")

    monkeypatch.setattr(paramiko.SSHClient, "connect", check_connect)
    with pytest.raises(OSError, match="conexão simulada"):
        remediation.runner_ssh("192.0.2.10", "polaris", "chave")("true", 5)


def test_comando_nativo_fora_da_lista_e_recusado():
    with pytest.raises(ValueError, match="não autorizado"):
        prepare_command("/usr/sbin/logrotate -f /etc/logrotate.conf", load_catalog(), 60)


def test_comando_vazio_e_rejeitado():
    with pytest.raises(ValueError, match="vazio"):
        prepare_command("   ", load_catalog(), 60)


# ---------------------------------------------------------------------------
# Decisão de sucesso
# ---------------------------------------------------------------------------


def test_sucesso_exige_confirmacoes_consecutivas_do_verificador():
    exe, runner = executor([0, 0, 0])
    resultado = exe("systemctl restart nginx", verificador="verify_service.sh nginx")

    assert resultado.status == "sucesso"
    assert resultado.saudavel is True
    assert runner.chamadas[0].endswith("/usr/bin/systemctl restart nginx")
    assert runner.chamadas[1] == "/usr/bin/timeout -k 5s 30s /usr/bin/bash -s -- nginx"
    assert runner.entradas[1] == load_catalog().get("verify_service.sh").content


def test_comando_bem_sucedido_com_servico_ainda_caido_nao_fecha_o_incidente():
    """O caso que o código de retorno esconde: o reinício retorna zero e o serviço não sobe."""
    exe, _ = executor([0, 1, 1, 1, 1, 1])
    resultado = exe("systemctl restart nginx", verificador="verify_service.sh nginx")

    assert resultado.status == "falha"
    assert resultado.saudavel is False
    assert "não confirmou o restabelecimento" in resultado.erro


def test_servico_que_oscila_nao_e_dado_como_resolvido():
    """Uma confirmação isolada entre falhas não basta: exige-se acertos consecutivos."""
    exe, _ = executor([0, 0, 1, 0, 1, 0])
    resultado = exe("systemctl restart nginx", verificador="verify_service.sh nginx",
                    timeout_segundos=30)
    assert resultado.saudavel is False


def test_ausencia_de_verificador_impede_conclusao():
    exe, _ = executor([0])
    resultado = exe("systemctl restart nginx", verificador=None)

    assert resultado.saudavel is False
    assert "sem verificador declarado" in resultado.erro


# ---------------------------------------------------------------------------
# Recusas e falhas
# ---------------------------------------------------------------------------


def test_recusa_do_script_nao_dispara_verificacao():
    """Código 2 é o script se recusando a agir: alvo fora da lista autorizada."""
    exe, runner = executor([(2, "", "candidato 'postgres' fora da lista autorizada")])
    resultado = exe("kill_target_process.sh stress-ng", verificador="verify_cpu.sh")

    assert resultado.status == "falha"
    assert "fora da lista autorizada" in resultado.erro
    assert len(runner.chamadas) == 1


def test_timeout_e_registrado_com_estado_proprio():
    exe, _ = executor([TimeoutError()])
    resultado = exe("disk_cleanup.sh /mnt/polaris_test", verificador="verify_disk.sh /mnt/polaris_test",
                    timeout_segundos=60)

    assert resultado.status == "timeout"
    assert resultado.exit_code is None
    assert "60s" in resultado.erro


def test_host_inacessivel_vira_falha_com_causa_legivel():
    exe, _ = executor([OSError("connection refused")])
    resultado = exe("systemctl restart nginx", verificador="verify_service.sh nginx")

    assert resultado.status == "falha"
    assert "falha de execução remota" in resultado.erro
    assert "connection refused" in resultado.erro


def test_verificador_inacessivel_nao_fecha_o_incidente():
    exe, _ = executor([0, OSError("conexão perdida")])
    resultado = exe("systemctl restart nginx", verificador="verify_service.sh nginx")

    assert resultado.saudavel is False
    assert "verificador não pôde ser executado" in resultado.erro


def test_saida_do_comando_e_preservada_na_auditoria():
    exe, _ = executor([(0, "uso depois: 62%", ""), 0, 0])
    resultado = exe("disk_cleanup.sh /mnt/polaris_test",
                    verificador="verify_disk.sh /mnt/polaris_test")

    assert resultado.status == "sucesso"
    assert resultado.saida == "uso depois: 62%"


# ---------------------------------------------------------------------------
# Integração com o serviço
# ---------------------------------------------------------------------------


def test_ciclo_completo_usa_o_verificador_gravado(conn, kb, config, alerta, monkeypatch):
    """O verificador aplicado vem da trilha de auditoria, não da base de conhecimento atual."""
    from src.db import queries
    from src.engine.service import decidir, ingerir
    from src.engine import action_plans
    from datetime import datetime, timezone
    monkeypatch.setattr(action_plans, "collect_evidence", lambda alert: {
        "tipo": "service_down", "coletado_em": datetime.now(timezone.utc).isoformat(),
        "estado_servico": "inactive", "indicios": []})

    ing = ingerir(conn, alerta("service_down", id_evento="rem-1"), kb, config,
                  usar_historico=False)
    registro = queries.obter_incidente(conn, ing.incidente_id)
    assert registro["comando_verificacao"] == "verify_service.sh nginx"

    plan = ing.sugestao.plan
    action = plan["opcoes"][0]
    decidir(conn, ing.incidente_id, True, "tester", versao_scripts=load_catalog().sha256,
            action=action, plan_version=plan["versao"])
    exe, runner = executor([0, 0, 0])

    from src.engine.service import executar
    executar(conn, ing.incidente_id, exe, timeout_segundos=120)

    assert "/usr/bin/python3 - " in runner.chamadas[0]
    assert runner.entradas[0] == load_catalog().get("apply_action.py").content
    assert runner.chamadas[1:] == ["/usr/bin/timeout -k 5s 30s /usr/bin/bash -s -- nginx"] * 2
    assert runner.entradas[1:] == [load_catalog().get("verify_service.sh").content] * 2
    final = queries.obter_incidente(conn, ing.incidente_id)
    assert final["status_execucao"] == "sucesso"
    assert final["ts_conclusao"] is not None


def test_executor_padrao_e_simulado_sem_host_configurado(monkeypatch):
    """Sem host alvo configurado, aprovar registra a decisão e não toca em máquina nenhuma."""
    from src.engine.config import get_settings
    from src.engine.service import ExecutorSimulado, executor_padrao

    monkeypatch.setenv("TARGET_SSH_HOST", "")
    get_settings.cache_clear()
    try:
        assert isinstance(executor_padrao(), ExecutorSimulado)
    finally:
        get_settings.cache_clear()


def test_queries_operacionais_usam_clock_timestamp_e_nao_now_congelado(alerta, kb, config):
    """Marcos usam o relógio real; janelas F3/F4 têm limite estável por consulta."""
    from datetime import datetime, timezone
    from src.db import queries
    from src.engine.engine import analisar
    from src.engine.service import ExecutorSimulado, executar

    sqls: list[str] = []

    class CursorFalso:
        def __init__(self):
            self.rowcount = 1
            self._row = {"id": 1, "n": 2, "sucessos": 2, "k": 1}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql: str, params=None):
            sqls.append(" ".join(sql.split()))

        def fetchone(self):
            return self._row

    class ConnFalsa:
        def __init__(self):
            self.commits = 0

        def cursor(self):
            return CursorFalso()

        def commit(self):
            self.commits += 1

    conn = ConnFalsa()
    agora = datetime.now(timezone.utc)
    a_sem_regra = alerta("sem_regra", id_evento="")
    a_com_regra = alerta("service_down", id_evento="")
    sug = analisar(a_com_regra, kb, config)
    queries.criar_incidente(conn, a_sem_regra, sugestao=None)
    queries.criar_incidente(conn, a_com_regra, sugestao=sug)
    queries.marcar_exibicao(conn, 1)
    queries.registrar_decisao(conn, 1, True, "operador", None)
    queries.registrar_execucao(conn, 1, "sucesso", 0, "ok", None, concluir=True)
    queries.encerrar_por_origem(conn, 1)
    queries.historico_regra(conn, "R003", 90)
    queries.recorrencia(conn, "vm-alvo", "R003", 30)

    assert len(sqls) == 10
    for trecho in sqls[:8]:
        assert "clock_timestamp()" in trecho
        assert "statement_timestamp()" not in trecho
    for trecho in sqls[8:]:
        assert "statement_timestamp()" in trecho
        assert "clock_timestamp()" not in trecho
    for trecho in sqls:
        assert "NOW()" not in trecho

    # Verifica também que service.executar relê a aprovação antes do executor e persiste ao final.
    ordem: list[str] = []

    class ConnExecucao(ConnFalsa):
        def cursor(self):
            class Cur(CursorFalso):
                def execute(self, sql: str, params=None):
                    compacto = " ".join(sql.split())
                    sqls.append(compacto)
                    if compacto.startswith("SELECT * FROM audit_log"):
                        ordem.append("obter_incidente")
                    elif compacto.startswith("UPDATE audit_log SET status_execucao"):
                        ordem.append("registrar_execucao")

                def fetchone(self):
                    return {
                        "id": 42,
                        "decisao_humana": True,
                        "ts_aprovacao": agora,
                        "status_execucao": "executando",
                        "comando_executado": "systemctl restart nginx",
                        "comando_verificacao": "verify_service.sh nginx",
                        "versao_scripts": None,
                    }

            return Cur()

        def commit(self):
            ordem.append("commit")
            super().commit()

    conn_exec = ConnExecucao()
    simulado = ExecutorSimulado(saudavel=True)

    def executor_rastreado(cmd: str, verificador: str | None = None, timeout_segundos: int = 60):
        ordem.append("executor")
        return simulado(cmd, verificador=verificador, timeout_segundos=timeout_segundos)

    res = executar(conn_exec, 42, executor_rastreado)
    assert res.status == "sucesso"
    assert ordem == ["obter_incidente", "executor", "registrar_execucao", "commit"]
    assert "ts_conclusao = CASE WHEN %s THEN clock_timestamp() ELSE ts_conclusao END" in sqls[-1]
