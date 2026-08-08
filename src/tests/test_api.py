"""Testes da API e do fluxo Human-in-the-Loop.

Exigem PostgreSQL de pé, pela mesma razão dos testes de persistência; sem ele, são pulados.
"""

from __future__ import annotations

import pytest

ALERTA_SERVICO = {
    "tipo_alerta": "service_down",
    "hostname": "vm-alvo-01",
    "severidade": "critica",
    "metrica": "proc.num[nginx]",
    "valor": 0,
    "texto": "nginx: service nginx is not running. Active: inactive (dead)",
}
ALERTA_DISCO = {
    "tipo_alerta": "disk_full",
    "hostname": "vm-alvo-01",
    "severidade": "alta",
    "metrica": "vfs.fs.size[/mnt/polaris_test,pused]",
    "valor": 97.4,
    "texto": "Filesystem /mnt/polaris_test: No space left on device",
}


def _criar(cliente, alerta=None, **extra):
    corpo = {**(alerta or ALERTA_SERVICO), **extra}
    resposta = cliente.post("/debug/simulate-alert", json=corpo)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_health_reporta_banco_e_base(cliente):
    dados = cliente.get("/health").json()
    assert dados["status"] == "ok"
    assert dados["db"] == "ok"
    assert dados["kb"] == "ok"
    assert dados["versao_kb"] == "1.0.0"


def test_interface_e_documentacao_sao_servidas(cliente):
    assert cliente.get("/").status_code == 200
    assert cliente.get("/app.js").status_code == 200
    assert cliente.get("/style.css").status_code == 200
    assert cliente.get("/docs").status_code == 200


def test_fluxo_completo_de_aprovacao(cliente):
    criado = _criar(cliente, id_evento="api-fluxo")
    assert criado["regra"] == "R003"
    assert criado["banda"] == "alta"
    incidente = criado["incidente_id"]

    assert cliente.get("/api/v1/incidentes").json()["total"] == 1
    assert cliente.patch(f"/api/v1/incidentes/{incidente}/exibicao").json()["status"] == "registrado"

    decisao = cliente.post(f"/api/v1/incidentes/{incidente}/decisao",
                           json={"aprovado": True, "operador": "tester"})
    assert decisao.status_code == 202
    assert decisao.json()["status"] == "executando"

    resultado = cliente.get(f"/api/v1/incidentes/{incidente}/resultado").json()
    assert resultado["status"] == "sucesso"
    assert resultado["mttr_segundos"] is not None


def test_detalhe_traz_o_trace_de_explicabilidade(cliente):
    """A explicabilidade precisa chegar à interface pronta para leitura, não como JSON cru."""
    incidente = _criar(cliente, ALERTA_DISCO, id_evento="api-trace")["incidente_id"]
    d = cliente.get(f"/api/v1/incidentes/{incidente}").json()

    assert d["regra"] == "R001"
    assert d["diagnostico"]
    assert d["comando"] == "disk_cleanup.sh /mnt/polaris_test"
    assert d["rollback"]
    assert len(d["fatores"]) == 5
    assert all({"id", "nome", "valor", "motivo"} <= set(f) for f in d["fatores"])
    assert d["evidencias"]["metrica"]["cruzou"] is True
    assert d["evidencias"]["texto"]["casou"] is True
    assert d["versao_kb"] and d["versao_motor"]


def test_rejeicao_nao_executa_e_guarda_o_motivo(cliente):
    incidente = _criar(cliente, id_evento="api-rejeita")["incidente_id"]
    resposta = cliente.post(f"/api/v1/incidentes/{incidente}/decisao",
                            json={"aprovado": False, "operador": "tester",
                                  "motivo": "janela de manutenção"})
    assert resposta.json()["status"] == "rejeitado"

    d = cliente.get(f"/api/v1/incidentes/{incidente}").json()
    assert d["status"] == "rejeitado"
    assert d["motivo_rejeicao"] == "janela de manutenção"
    assert d["ts_conclusao"] is None


def test_segunda_decisao_gera_conflito(cliente):
    incidente = _criar(cliente, id_evento="api-conflito")["incidente_id"]
    cliente.post(f"/api/v1/incidentes/{incidente}/decisao",
                 json={"aprovado": True, "operador": "tester"})
    resposta = cliente.post(f"/api/v1/incidentes/{incidente}/decisao",
                            json={"aprovado": True, "operador": "outro"})
    assert resposta.status_code == 409
    assert resposta.json()["erro"] == "conflito_de_estado"


def test_exibicao_repetida_nao_reescreve_o_marco(cliente):
    incidente = _criar(cliente, id_evento="api-exibicao")["incidente_id"]
    assert cliente.patch(f"/api/v1/incidentes/{incidente}/exibicao").json()["status"] == "registrado"
    primeiro = cliente.get(f"/api/v1/incidentes/{incidente}").json()["ts_exibicao"]
    assert cliente.patch(f"/api/v1/incidentes/{incidente}/exibicao").json()["status"] == "ja_registrado"
    assert cliente.get(f"/api/v1/incidentes/{incidente}").json()["ts_exibicao"] == primeiro


def test_alerta_sem_regra_responde_no_match(cliente):
    resposta = cliente.post("/debug/simulate-alert",
                            json={"tipo_alerta": "oom_killer", "hostname": "vm-alvo-01",
                                  "texto": "Out of memory: Killed process 4127 (java)"})
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["status"] == "no_match"
    assert corpo["regra"] is None
    assert "nenhuma regra compatível" in corpo["motivo"]


def test_evento_reentregue_nao_duplica(cliente):
    primeiro = _criar(cliente, id_evento="api-duplicado")
    segundo = cliente.post("/debug/simulate-alert",
                           json={**ALERTA_SERVICO, "id_evento": "api-duplicado"}).json()
    assert segundo["status"] == "duplicate"
    assert segundo["incidente_id"] == primeiro["incidente_id"]


def test_incidente_inexistente_responde_404(cliente):
    resposta = cliente.get("/api/v1/incidentes/99999")
    assert resposta.status_code == 404
    assert resposta.json()["erro"] == "incidente_inexistente"
    assert "não encontrado" in resposta.json()["mensagem"]


def test_recorrencia_derruba_a_banda_pela_api(cliente):
    """O caminho completo, como o operador veria na tela: alta, média, baixa."""
    bandas = []
    for i in range(3):
        criado = _criar(cliente, id_evento=f"api-flap-{i}")
        bandas.append(criado["banda"])
        cliente.post(f"/api/v1/incidentes/{criado['incidente_id']}/decisao",
                     json={"aprovado": True, "operador": "tester"})
    assert bandas == ["alta", "media", "baixa"]


def test_aviso_de_recorrencia_chega_na_interface(cliente):
    for i in range(2):
        criado = _criar(cliente, id_evento=f"api-aviso-{i}")
        cliente.post(f"/api/v1/incidentes/{criado['incidente_id']}/decisao",
                     json={"aprovado": True, "operador": "tester"})
    terceiro = _criar(cliente, id_evento="api-aviso-3")
    d = cliente.get(f"/api/v1/incidentes/{terceiro['incidente_id']}").json()

    f4 = next(f for f in d["fatores"] if f["id"] == "F4")
    assert f4["valor"] < 1
    assert "flapping" in f4["motivo"]
    assert d["banda"] == "baixa"


def test_regras_sao_expostas_para_leitura(cliente):
    dados = cliente.get("/api/v1/regras").json()
    assert dados["versao_kb"] == "1.0.0"
    assert len(dados["regras"]) == 3
    assert all("{" not in r["comando"] for r in dados["regras"])


def test_reload_da_base_responde(cliente):
    dados = cliente.post("/api/v1/regras/reload").json()
    assert dados["status"] == "recarregada"
    assert dados["regras"] == 3


def test_kpis_expõem_as_quatro_visoes(cliente):
    dados = cliente.get("/api/v1/kpis").json()
    assert set(dados) == {"kpi01_mttr", "kpi02_passos", "kpi03_acerto", "decomposicao_mttr"}


def test_simulacao_indisponivel_sem_modo_debug(cliente_sem_debug):
    resposta = cliente_sem_debug.post("/debug/simulate-alert", json=ALERTA_SERVICO)
    assert resposta.status_code == 404
    assert resposta.json()["erro"] == "endpoint_indisponivel"


def test_health_declara_modo_debug_ligado(cliente):
    """A interface usa esta flag para decidir se mostra o botão de simulação.

    Sondar o endpoint de simulação para descobrir isso criaria um incidente a cada carregamento da
    página, contaminando a trilha de auditoria.
    """
    assert cliente.get("/health").json()["debug"] is True


def test_health_declara_modo_debug_desligado(cliente_sem_debug):
    assert cliente_sem_debug.get("/health").json()["debug"] is False


def test_decisao_exige_operador(cliente):
    incidente = _criar(cliente, id_evento="api-sem-operador")["incidente_id"]
    resposta = cliente.post(f"/api/v1/incidentes/{incidente}/decisao", json={"aprovado": True})
    assert resposta.status_code == 422
