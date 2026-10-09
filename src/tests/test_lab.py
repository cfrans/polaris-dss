"""Host launcher checks with fake Docker; no service, key or laboratory access."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from experiment import lab


IMAGE = "sha256:" + "b" * 64
SHA = "a" * 40


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "ROOT", tmp_path)
    service_key, admin_key = tmp_path / "service.key", tmp_path / "admin.key"
    service_key.write_bytes(b"fake service fixture")
    admin_key.write_bytes(b"fake admin fixture")
    admin_key.chmod(0o600)
    api_env = {"TARGET_SSH_USER": "polaris", "TARGET_SSH_HOST": "fixture.invalid",
               "TARGET_SSH_KEY_PATH": "/run/secrets/polaris_ssh_key", "POLARIS_CONFIDENCE_HISTORY": "false",
               "POLARIS_DEBUG": "false", "DB_HOST": "polaris-db", "DB_PORT": "5432",
               "DB_USER": "postgres", "DB_NAME_AUDIT": "fixture"}
    recon_env = {key: value for key, value in api_env.items() if not key.startswith("TARGET_") and key != "POLARIS_DEBUG"}
    config = {"services": {"polaris-api": {"environment": api_env, "volumes": [
        {"target": "/run/secrets/polaris_ssh_key", "type": "bind", "source": str(service_key)}]},
        "polaris-reconciler": {"environment": recon_env}}}
    state = SimpleNamespace(config=config, api_env=dict(api_env), recon_env=dict(recon_env),
                            code=0, commands=[], overlays=[], admin_key=admin_key, service_key=service_key)

    def capture(command):
        if command[:2] == ["git", "rev-parse"]:
            return SHA
        if command[:2] == ["git", "diff"]:
            return ""
        if command[:2] == ["docker", "inspect"]:
            return "true " + IMAGE
        if "config" in command:
            return json.dumps(state.config)
        if "exec" in command:
            return json.dumps(state.recon_env if "polaris-reconciler" in command else state.api_env)
        if "ps" in command:
            return "fake-api-id"
        raise AssertionError(command)

    def run(command, **kwargs):
        state.commands.append(command)
        if "--rm" in command:
            overlay = Path(command[command.index("run") - 1])
            state.overlays.append(json.loads(overlay.read_text()))
        if "stdout" in kwargs:
            kwargs["stdout"].write(b"fake dump bytes")
        return SimpleNamespace(returncode=state.code)

    monkeypatch.setattr(lab, "capture", capture)
    monkeypatch.setattr(lab.subprocess, "run", run)
    return state


def admin_options(state):
    return ["--admin-user", "root", "--admin-key-file", str(state.admin_key)]


def run_options(state):
    return ["run", "--scenario", "service_down", "--arm", "hitl", "--repetition", "1",
            "--operator", "fixture operator", "--system-version", "fixture", "--commit-sha", SHA,
            "--timeout", "300", *admin_options(state)]


def test_check_pins_api_image_mounts_admin_readonly_and_does_not_reset(workspace):
    assert lab.main(["check", "--scenario", "service_down", *admin_options(workspace)]) == 0
    command = workspace.commands[0]
    assert workspace.overlays[0]["services"]["polaris-api"]["image"] == IMAGE
    assert "--no-deps" in command and "--rm" in command and "--service-ports" not in command
    assert f"{workspace.admin_key}:{lab.ADMIN_MOUNT}:ro" in command
    assert command[-7:] == ["--check", "--scenario", "service_down", "--admin-user", "root", "--admin-key-file", lab.ADMIN_MOUNT]
    assert "run" not in command[command.index("polaris-api") + 1:]
    assert "--reset-run-id" not in command


@pytest.mark.parametrize("unsafe", ["mode", "same-path", "copied-key", "same-user"])
def test_admin_separation_refused_before_creating_container(workspace, unsafe):
    options = admin_options(workspace)
    if unsafe == "mode":
        workspace.admin_key.chmod(0o644)
    elif unsafe == "same-path":
        workspace.service_key.chmod(0o600)
        options[-1] = str(workspace.service_key)
    elif unsafe == "copied-key":
        workspace.admin_key.write_bytes(workspace.service_key.read_bytes())
    else:
        options[1] = "polaris"
    assert lab.main(["check", "--scenario", "cpu_high", *options]) == 2
    assert workspace.commands == []


@pytest.mark.parametrize("problem", ["history-api", "history-reconciler", "debug", "target-drift"])
def test_uncontrolled_or_stale_runtime_cannot_inject(workspace, problem):
    if problem == "history-api":
        workspace.api_env["POLARIS_CONFIDENCE_HISTORY"] = "true"
        workspace.config["services"]["polaris-api"]["environment"]["POLARIS_CONFIDENCE_HISTORY"] = "true"
    elif problem == "history-reconciler":
        workspace.recon_env["POLARIS_CONFIDENCE_HISTORY"] = "true"
        workspace.config["services"]["polaris-reconciler"]["environment"]["POLARIS_CONFIDENCE_HISTORY"] = "true"
    elif problem == "debug":
        workspace.api_env["POLARIS_DEBUG"] = "true"
        workspace.config["services"]["polaris-api"]["environment"]["POLARIS_DEBUG"] = "true"
    else:
        workspace.api_env["TARGET_SSH_HOST"] = "stale.invalid"
    assert lab.main(run_options(workspace)) == 2
    assert workspace.commands == []


def test_controller_error_propagates_without_reset_or_assessment(workspace):
    workspace.code = 2
    assert lab.main(run_options(workspace)) == 2
    assert len(workspace.commands) == 1
    assert "experiment.scenarios.service_controller" in workspace.commands[0]
    assert "experiment.rounds" not in workspace.commands[0]
    assert "reset" not in workspace.commands[0]


def test_assessment_only_mounts_json_and_preserves_literal_ids(workspace, tmp_path):
    record = tmp_path / "assessment.json"
    record.write_text("{}")
    assert lab.main(["assess", "--run-id", "123", "--record-file", str(record)]) == 0
    command = workspace.commands[0]
    assert str(workspace.admin_key) not in " ".join(command)
    assert f"{record}:/run/lab/assessment.json:ro" in command
    assert command[-4:] == ["--run-id", "123", "--record-file", "/run/lab/assessment.json"]


def test_report_mounts_excluded_analysis_and_persistent_host_output(workspace, tmp_path):
    output = tmp_path / "evidence"
    assert lab.main(["report", "--output", str(output), "--kind", "synthetic"]) == 0
    command = workspace.commands[0]
    assert f"{lab.ROOT / 'experiment/analysis'}:/app/experiment/analysis:ro" in command
    assert f"{output}:/lab-output" in command
    assert lab.ADMIN_MOUNT not in " ".join(command)
    assert "--no-graphs" in command
    assert lab.main(["report", "--output", str(output), "--kind", "synthetic"]) == 2
    assert len(workspace.commands) == 1


def test_dump_refuses_overwrite_and_preserves_partial_failure(workspace, tmp_path):
    output = tmp_path / "before.dump"
    assert lab.main(["backup", "--output", str(output)]) == 0
    assert output.read_bytes() == b"fake dump bytes"
    assert output.stat().st_mode & 0o077 == 0
    assert lab.main(["backup", "--output", str(output)]) == 2
    assert len(workspace.commands) == 1
    workspace.code = 1
    failed = tmp_path / "failed.dump"
    assert lab.main(["backup", "--output", str(failed)]) == 2
    assert not failed.exists()
    assert failed.with_name("failed.dump.partial").exists()


def test_paths_resolve_from_script_instead_of_calling_directory(workspace, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert lab.host_path("evidence/round.json") == lab.ROOT / "evidence/round.json"
