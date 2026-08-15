"""Executor de remediação.

Nenhum teste abre conexão SSH: o executor recebe um `Runner` dublê, que registra os comandos
recebidos e devolve os códigos de saída combinados. É o que permite exercitar as decisões — quando
fechar o incidente, quando recusar, quando insistir na verificação — sem host remoto.
"""

from __future__ import annotations

import pytest

from src.engine.remediation import ExecutorRemoto, montar_comando


class RunnerDuble:
    """Devolve os códigos de saída na ordem combinada e guarda o que foi executado."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas: list[str] = []

    def __call__(self, comando, timeout):
        self.chamadas.append(comando)
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
    return ExecutorRemoto(runner=runner, intervalo_verificacao=0, **kwargs), runner


# ---------------------------------------------------------------------------
# Montagem do comando
# ---------------------------------------------------------------------------


def test_script_e_resolvido_no_diretorio_controlado():
    """A forma final precisa casar com a entrada correspondente no sudoers do host alvo."""
    assert montar_comando("disk_cleanup.sh /mnt/polaris_test") == \
        "sudo /opt/polaris/bin/disk_cleanup.sh /mnt/polaris_test"


def test_binario_do_sistema_nao_recebe_diretorio_de_scripts():
    assert montar_comando("systemctl restart nginx") == "sudo systemctl restart nginx"


def test_verificador_roda_sem_privilegio_elevado():
    """Verificador consulta estado e não altera nada: não precisa entrar no sudoers."""
    assert montar_comando("verify_service.sh nginx", com_sudo=False) == \
        "/opt/polaris/bin/verify_service.sh nginx"


def test_caminho_absoluto_e_preservado():
    assert montar_comando("/usr/sbin/logrotate -f /etc/logrotate.conf") == \
        "sudo /usr/sbin/logrotate -f /etc/logrotate.conf"


def test_comando_vazio_e_rejeitado():
    with pytest.raises(ValueError, match="vazio"):
        montar_comando("   ")


# ---------------------------------------------------------------------------
# Decisão de sucesso
# ---------------------------------------------------------------------------


def test_sucesso_exige_confirmacoes_consecutivas_do_verificador():
    exe, runner = executor([0, 0, 0])
    resultado = exe("systemctl restart nginx", verificador="verify_service.sh nginx")

    assert resultado.status == "sucesso"
    assert resultado.saudavel is True
    assert runner.chamadas[0] == "sudo systemctl restart nginx"
    assert runner.chamadas[1] == "/opt/polaris/bin/verify_service.sh nginx"


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


def test_ciclo_completo_usa_o_verificador_gravado(conn, kb, config, alerta):
    """O verificador aplicado vem da trilha de auditoria, não da base de conhecimento atual."""
    from src.db import queries
    from src.engine.service import decidir, ingerir

    ing = ingerir(conn, alerta("service_down", id_evento="rem-1"), kb, config,
                  usar_historico=False)
    registro = queries.obter_incidente(conn, ing.incidente_id)
    assert registro["comando_verificacao"] == "verify_service.sh nginx"

    decidir(conn, ing.incidente_id, True, "tester")
    exe, runner = executor([0, 0, 0])

    from src.engine.service import executar
    executar(conn, ing.incidente_id, exe, timeout_segundos=120)

    assert runner.chamadas == [
        "sudo systemctl restart nginx",
        "/opt/polaris/bin/verify_service.sh nginx",
        "/opt/polaris/bin/verify_service.sh nginx",
    ]
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
