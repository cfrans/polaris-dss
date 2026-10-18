import base64
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="coletor Linux usa pwd")
def test_service_exit_evidence_is_literal_and_not_a_root_cause(monkeypatch):
    from src.scripts import collect_evidence
    commands = []
    def read(args):
        commands.append(args)
        if "--property=ActiveState" in args:
            return "inactive\n"
        if any(a.startswith("--property=Result,") for a in args):
            return "Result=success\nExecMainCode=1\nExecMainStatus=0\nInactiveEnterTimestamp=Fri 2026-10-16 23:49:12 UTC\n"
        return "Stopped nginx.\n"
    monkeypatch.setattr(collect_evidence, "command", read)
    monkeypatch.setattr(collect_evidence.os, "open", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    result = collect_evidence.service()
    assert result["estado_servico"] == "inactive"
    assert result["saida_servico"]["codigo"] == "0"
    assert result["indicios"] == []
    assert all("start" not in c and "restart" not in c for c in commands)

from src.engine.action_plans import build_plan, choose_action, verify_plan


def evidence(**extra):
    return {"coletado_em": datetime.now(timezone.utc).isoformat(),
            "tipo": "disk_full", "arquivos": [], "completo": True, **extra}


def file_info(name="old.log.gz", age=8 * 86400):
    return {"caminho": "/mnt/polaris_test/" + name, "bytes": 100,
            "mtime_ns": 1, "ctime_ns": 2, "inode": 3, "dispositivo": 4,
            "uid": 0, "modo": 0o600, "links": 1, "idade_s": age,
            "aberto": False, "proprietario": "root"}


def test_plan_binds_exact_file_and_never_uses_alert_as_a_command(kb, alerta, config):
    from src.engine.engine import analisar
    s = analisar(alerta("disk_full"), kb, config)
    plan = build_plan(s, evidence(arquivos=[file_info()], espaco_livre=10000))
    verify_plan(plan)
    a = choose_action(plan, plan["versao"], plan["opcoes"][0]["id"])
    assert a["alvo"]["caminho"] == "/mnt/polaris_test/old.log.gz"
    assert a["destrutiva"] is True
    assert "logrotate" not in a["comando"]
    payload = json.loads(base64.urlsafe_b64decode(a["comando"].split()[1]))
    assert payload["alvo"] == a["alvo"]


@pytest.mark.parametrize("change", [{"uid": 1000}, {"links": 2}, {"modo": 0o666},
                                     {"idade_s": 10}, {"caminho": "/var/log/old.log.gz"}])
def test_disk_rejects_unsafe_candidates(kb, alerta, config, change):
    from src.engine.engine import analisar
    f = file_info(); f.update(change)
    plan = build_plan(analisar(alerta("disk_full"), kb, config), evidence(arquivos=[f]))
    assert plan["opcoes"] == []


def test_compress_requires_closed_log_and_free_space(kb, alerta, config):
    from src.engine.engine import analisar
    s = analisar(alerta("disk_full"), kb, config)
    f = file_info("closed.log")
    p = build_plan(s, evidence(arquivos=[f], espaco_livre=10000))
    assert p["opcoes"][0]["operacao"] == "compress"
    f["aberto"] = True
    assert not build_plan(s, evidence(arquivos=[f], espaco_livre=10000))["opcoes"]


def test_plan_rejects_tampering_wrong_version_and_unoffered_choice(kb, alerta, config):
    from src.engine.engine import analisar
    p = build_plan(analisar(alerta("disk_full"), kb, config), evidence(arquivos=[file_info()]))
    with pytest.raises(ValueError): choose_action(p, "wrong", p["opcoes"][0]["id"])
    with pytest.raises(ValueError): choose_action(p, p["versao"], "forged")
    p["opcoes"][0]["alvo"]["caminho"] = "/etc/passwd"
    with pytest.raises(ValueError): verify_plan(p)


def test_nginx_known_error_blocks_blind_restart(kb, alerta, config):
    from src.engine.engine import analisar
    s = analisar(alerta("service_down"), kb, config)
    p = build_plan(s, evidence(tipo="service_down", estado_servico="failed",
                              indicios=[{"codigo": "configuracao", "trecho": "invalid parameter"}]))
    assert not p["opcoes"]
    p = build_plan(s, evidence(tipo="service_down", estado_servico="inactive", indicios=[]))
    assert {a["operacao"] for a in p["opcoes"]} == {"start", "restart"}


def test_unavailable_diagnostics_never_fall_back_to_destructive_action(kb, alerta, config):
    from src.engine.engine import analisar
    p = build_plan(analisar(alerta("cpu_high"), kb, config), {"erro": "indisponivel"})
    assert not p["opcoes"]


@pytest.mark.parametrize("name,cpu_pct,offered", [
    ("stress-ng-cpu", 89.99, True),    # incident 305: below the host threshold, still the clear cause
    ("stress-ng-cpu", 92.99, True),    # incident 303
    ("stress-ng-cpu", 50.0, True),
    ("stress-ng-cpu", 49.99, False),   # not the dominant consumer of one CPU
    ("python3", 99.0, False),          # outside the frozen allowlist
])
def test_cpu_termination_requires_allowed_dominant_process_not_the_host_threshold(
        kb, alerta, config, name, cpu_pct, offered):
    from src.engine.engine import analisar
    p = build_plan(analisar(alerta("cpu_high"), kb, config), evidence(
        tipo="cpu_high", processo={"pid": 216618, "nome": name, "inicio": "237274638", "cpu_pct": cpu_pct}))
    assert [a["operacao"] for a in p["opcoes"]] == (["terminate"] if offered else [])
    if offered:
        assert p["opcoes"][0]["alvo"]["pid"] == 216618 and p["opcoes"][0]["destrutiva"] is True


def test_preference_tiebreak_and_optional_discount_are_distinct(kb, alerta, config):
    from src.engine.engine import analisar
    s = analisar(alerta("service_down"), kb, config)
    ev = evidence(tipo="service_down", estado_servico="inactive", indicios=[])
    pref = {"modo_preferencia": "desempate", "desconto_maximo": .1, "minimo_escolhas": 5, "versao": 2}
    p = build_plan(s, ev, pref, {"restart": 6}, True, config)
    assert p["opcoes"][0]["operacao"] == "restart"
    assert all(a["confianca"] == s.confianca for a in p["opcoes"])
    pref["modo_preferencia"] = "desconto"
    p = build_plan(s, ev, pref, {"restart": 6}, True, config)
    assert p["opcoes"][0]["confianca"] == s.confianca
    assert p["opcoes"][1]["confianca"] == round(s.confianca * .9, 4)
    p = build_plan(s, ev, pref, {"restart": 6}, False, config)
    assert all(a["confianca"] == s.confianca and not a["preferencia"]["aplicada"] for a in p["opcoes"])


def test_failed_action_loses_confidence_without_penalizing_other_option(kb, alerta, config):
    from src.engine.engine import analisar
    s = analisar(alerta("service_down"), kb, config)
    p = build_plan(s, evidence(tipo="service_down", estado_servico="inactive", indicios=[]),
                   history_enabled=True, config=config,
                   outcomes={"start": {"n": 5, "sucessos": 1}})
    assert p["opcoes"][0]["operacao"] == "restart"
    assert p["opcoes"][1]["confianca"] == round(s.confianca * .75, 4)


def test_rule_ranking_uses_each_candidate_history(kb, alerta, config):
    from src.engine.engine import analisar
    from src.engine.history import Historico, HistoricoRegra
    from src.engine.knowledge_base import KnowledgeBase
    first = kb.por_id("R003")
    second = replace(first, id="R004", confianca_base=.9, ordem=3)
    many = KnowledgeBase(kb.versao_kb, (first, second))
    s = analisar(alerta("service_down"), many, config,
                 {"R003": Historico(regra=HistoricoRegra(5, 1)), "R004": Historico()})
    assert s.rule.id == "R004"
    assert s.trace.regras_candidatas_descartadas[0]["regra"] == "R003"


@pytest.fixture
def planned_incident(cliente, conn, monkeypatch):
    from src.db import queries
    from src.engine import action_plans
    queries.save_preferences(conn, "desempate", .1, 5)
    monkeypatch.setattr(action_plans, "collect_evidence", lambda alert:
                        evidence(tipo="service_down", estado_servico="inactive", indicios=[]))
    created = cliente.post("/debug/simulate-alert", json={
        "tipo_alerta": "service_down", "hostname": "vm-alvo", "texto": "Active: inactive",
        "metrica": "proc.num[nginx]", "severidade": "alta", "id_evento": "plan-test"})
    assert created.status_code == 201
    incident = created.json()["incidente_id"]
    detail = cliente.get(f"/api/v1/incidentes/{incident}").json()
    assert len(detail["plano"]["opcoes"]) == 2
    return incident, detail["plano"]


def approval(plan, option=None):
    from src.engine.script_catalog import load_catalog
    return {"aprovado": True, "operador": "tester", "versao_scripts": load_catalog().sha256,
            "versao_plano": plan["versao"], "opcao_id": option or plan["opcoes"][0]["id"]}


def test_selected_alternative_is_persisted_before_executor(planned_incident, cliente, conn, monkeypatch):
    from src.api import routes
    from src.db import queries
    from src.engine.service import ResultadoExecucao
    incident, plan = planned_incident
    selected = plan["opcoes"][1]
    calls = []
    def executor(command, **kwargs):
        # Uma segunda conexão enxerga a decisão já commitada antes da chamada.
        from src.db.connection import conectar
        with conectar() as other:
            saved = queries.obter_incidente(other, incident)
        assert saved["decisao_humana"] is True and saved["ts_aprovacao"] is not None
        assert saved["explicabilidade"]["acao_escolhida"]["id"] == selected["id"]
        assert command == selected["comando"]
        calls.append(command)
        return ResultadoExecucao("sucesso", 0, saudavel=True)
    monkeypatch.setattr(routes, "executor_padrao", lambda catalog: executor)
    response = cliente.post(f"/api/v1/incidentes/{incident}/decisao", json=approval(plan, selected["id"]))
    assert response.status_code == 202 and len(calls) == 1
    d = cliente.get(f"/api/v1/incidentes/{incident}").json()
    assert d["acao_escolhida"]["id"] == selected["id"] and d["status"] == "sucesso"


@pytest.mark.parametrize("field,value", [("opcao_id", "forged"), ("versao_plano", "wrong")])
def test_api_never_approves_unoffered_or_changed_plan(planned_incident, cliente, conn, field, value):
    from src.db import queries
    incident, plan = planned_incident
    body = approval(plan); body[field] = value
    assert cliente.post(f"/api/v1/incidentes/{incident}/decisao", json=body).status_code == 409
    conn.rollback()
    assert queries.obter_incidente(conn, incident)["decisao_humana"] is None


def test_changing_preferences_invalidates_pending_plan(planned_incident, cliente, conn):
    from src.db import queries
    incident, plan = planned_incident
    pref = cliente.put("/api/v1/preferencias", json={"modo_preferencia": "desconto"})
    assert pref.status_code == 200 and pref.json()["versao"] > plan["preferencias"]["versao"]
    assert cliente.post(f"/api/v1/incidentes/{incident}/decisao", json=approval(plan)).status_code == 409
    conn.rollback()
    assert queries.obter_incidente(conn, incident)["decisao_humana"] is None
    updated = cliente.post(f"/api/v1/incidentes/{incident}/diagnostico")
    assert updated.status_code == 200 and updated.json()["versao"] != plan["versao"]
    d = cliente.get(f"/api/v1/incidentes/{incident}").json()
    assert d["plano"]["preferencias"]["modo_preferencia"] == "desconto"


def test_preferences_reject_out_of_range_input(cliente):
    assert cliente.put("/api/v1/preferencias", json={"desconto_maximo": .99}).status_code == 422
    assert cliente.put("/api/v1/preferencias", json={"modo_preferencia": "auto_approve"}).status_code == 422


def test_python_collector_cannot_be_called_by_remediation_executor():
    from src.engine.remediation import prepare_command
    from src.engine.script_catalog import load_catalog
    with pytest.raises(ValueError):
        prepare_command("collect_evidence.py disk_full", load_catalog(), 10)


@pytest.fixture
def disk_sandbox(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace
    from src.scripts import apply_action
    if os.name != "posix" or os.getuid() != 0:
        pytest.skip("exercício de filesystem Linux no container isolado como root")
    mount = tmp_path / "volume"
    mount.mkdir(mode=0o700)
    monkeypatch.setattr(apply_action, "MOUNT", str(mount))
    monkeypatch.setattr(apply_action.os.path, "ismount", lambda p: p == str(mount))
    original_stat = os.stat
    monkeypatch.setattr(apply_action.os, "stat", lambda p, **kw:
                        SimpleNamespace(st_dev=-1) if p == "/" else original_stat(p, **kw))
    def make(name, content=b"known log data\n" * 20):
        path = mount / name
        path.write_bytes(content)
        path.chmod(0o600)
        import time
        os.utime(path, (time.time() - 8 * 86400,) * 2)
        s = path.stat()
        return path, {"caminho": str(path), "dispositivo": s.st_dev, "inode": s.st_ino,
                      "bytes": s.st_size, "mtime_ns": s.st_mtime_ns, "ctime_ns": s.st_ctime_ns}
    return apply_action, make


def test_disk_executor_removes_only_approved_file(disk_sandbox):
    module, make = disk_sandbox
    path, target = make("old.log.gz")
    other, _ = make("older.log.gz")
    module.apply_disk("remove", target)
    assert not path.exists() and other.exists()


def test_disk_executor_refuses_changed_identity_and_symlink(disk_sandbox):
    module, make = disk_sandbox
    path, target = make("old.log.gz")
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="identidade"):
        module.apply_disk("remove", target)
    outside = path.parent.parent / "important"
    outside.write_text("keep")
    path.unlink(); path.symlink_to(outside)
    with pytest.raises(OSError): module.apply_disk("remove", target)
    assert outside.read_text() == "keep"


def test_compression_preserves_content_and_refuses_existing_destination(disk_sandbox, capsys):
    import gzip
    module, make = disk_sandbox
    path, target = make("closed.log")
    content = path.read_bytes()
    module.apply_disk("compress", target)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"compress: {path} -> {path}.gz"
    assert lines[1].startswith(f"tamanho: {module.human(len(content))} -> ")
    assert lines[2].startswith(f"volume {module.MOUNT}: ") and lines[2].endswith(" livres")
    assert not path.exists()
    assert gzip.decompress(path.with_name(path.name + ".gz").read_bytes()) == content
    second, other = make("closed.log")
    with pytest.raises(FileExistsError): module.apply_disk("compress", other)
    assert second.read_bytes() == content


def test_compression_refuses_log_opened_by_another_descriptor(disk_sandbox):
    module, make = disk_sandbox
    path, target = make("closed.log")
    with path.open("rb"):
        with pytest.raises(ValueError, match="aberto"):
            module.apply_disk("compress", target)
    assert path.exists() and not path.with_name(path.name + ".gz").exists()


def test_executor_reports_sizes_and_volume_like_df():
    from types import SimpleNamespace
    from src.scripts import apply_action
    assert apply_action.human(512) == "512 B"
    assert apply_action.human(400_000_000) == "381,5 MiB"
    assert apply_action.human(1_357_964) == "1,3 MiB"
    vfs = SimpleNamespace(f_blocks=1000, f_bfree=600, f_bavail=550, f_frsize=4096)
    assert apply_action.volume_line(vfs) == f"volume {apply_action.MOUNT}: 43% usado, 2,1 MiB livres"


def test_volume_is_reported_only_after_freed_blocks_appear():
    from types import SimpleNamespace
    from src.scripts import apply_action
    frees = iter([100, 100, 1100])            # stale, stale, then the freed 1000 blocks show up
    calls, clock = [], [0.0]
    line = apply_action.settled_volume_line(
        3, 0, 1000 * 4096 * 0.95,
        statvfs=lambda d: (lambda v: SimpleNamespace(f_blocks=2000, f_bfree=v, f_bavail=v, f_frsize=4096))(next(frees)),
        sync=lambda: calls.append("sync"), sleep=lambda s: clock.__setitem__(0, clock[0] + s),
        monotonic=lambda: clock[0])
    assert calls == ["sync"] and "ainda não aparece" not in line and line.endswith("livres")
    stale = apply_action.settled_volume_line(
        3, 100 * 4096, 1000 * 4096,
        statvfs=lambda d: SimpleNamespace(f_blocks=2000, f_bfree=100, f_bavail=100, f_frsize=4096),
        sync=lambda: None, sleep=lambda s: clock.__setitem__(0, clock[0] + s), monotonic=lambda: clock[0])
    assert stale.endswith("(o espaço liberado ainda não aparece no sistema de arquivos; confira com df)")


def test_process_identity_change_never_signals_another_process(monkeypatch):
    from src.scripts import apply_action
    calls = []
    monkeypatch.setattr(apply_action.os, "pidfd_open", lambda pid: 123, raising=False)
    monkeypatch.setattr(apply_action.os, "close", lambda descriptor: None)
    monkeypatch.setattr(apply_action, "process_identity", lambda pid: ("other", "new"))
    monkeypatch.setattr(apply_action.signal, "pidfd_send_signal", lambda *args: calls.append(args), raising=False)
    with pytest.raises(ValueError, match="identidade"):
        apply_action.apply_process({"pid": 500, "nome": "stress-ng", "inicio": "old"})
    assert not calls


def test_ingestion_is_persisted_before_remote_diagnostic_and_presentation_waits(conn, kb, config, alerta, monkeypatch):
    from src.engine import action_plans
    from src.engine.config import get_settings
    from src.engine.service import ingerir
    from src.db import queries
    from src.db.connection import conectar
    monkeypatch.setenv("TARGET_SSH_HOST", "192.168.0.152")
    get_settings.cache_clear()
    def collect(alert):
        with conectar() as other:
            with other.cursor() as cursor:
                cursor.execute("SELECT * FROM audit_log WHERE id_evento=%s", (alert.id_evento,))
                row = cursor.fetchone()
            assert row is not None and row["explicabilidade"]["plano"]["estado"] == "coletando"
            assert not queries.marcar_exibicao(other, row["id"])
        return evidence(tipo="service_down", estado_servico="inactive", indicios=[])
    monkeypatch.setattr(action_plans, "collect_evidence", collect)
    try:
        result = ingerir(conn, alerta("service_down", id_evento="persist-before-inspect"), kb, config)
        row = queries.obter_incidente(conn, result.incidente_id)
        assert row["explicabilidade"]["plano"]["estado"] == "concluido"
        assert queries.marcar_exibicao(conn, row["id"])
    finally:
        get_settings.cache_clear()


def test_concurrent_refresh_cannot_overwrite_newer_plan(planned_incident, conn):
    from copy import deepcopy
    from src.db import queries
    from src.engine.action_plans import digest
    incident, plan = planned_incident
    newer = deepcopy(plan); newer["aviso"] = "new inspection"
    newer["versao"] = digest({k:v for k,v in newer.items() if k != "versao"})
    assert queries.update_plan(conn, incident, newer, plan["versao"])
    assert not queries.update_plan(conn, incident, plan, plan["versao"])
    assert queries.obter_incidente(conn, incident)["explicabilidade"]["plano"]["versao"] == newer["versao"]
