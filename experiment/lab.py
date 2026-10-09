"""Host-side Compose launcher for explicit laboratory operations (standard library only)."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("service_down", "cpu_high", "disk_full")
ADMIN_ACTIONS = {"check", "prepare", "run", "reset"}
ADMIN_MOUNT = "/run/lab/admin_key"


def host_path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def compose(*args):
    return ["docker", "compose", "--project-directory", str(ROOT),
            "-f", str(ROOT / "docker-compose.yml"), *args]


def capture(command):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Falha na consulta ao Git/Docker; confira o checkout e o Compose no host.")
    return result.stdout.strip()


def running_image():
    container = capture(compose("ps", "-q", "polaris-api"))
    if not container or "\n" in container:
        raise ValueError("É necessária uma única API em execução neste Compose.")
    running, image = capture(["docker", "inspect", "--format", "{{json .State.Running}} {{.Image}}", container]).split()
    if running != "true":
        raise ValueError("A API não está em execução.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("Identificador da imagem inválido.")
    return image


def validate_admin(args):
    key = host_path(args.admin_key_file)
    if not key.is_file() or key.stat().st_mode & 0o077:
        raise ValueError("Chave administrativa deve existir e ser privada (modo 0600 ou 0400).")
    if any(char in str(key) for char in ":\n\r,"):
        raise ValueError("Caminho da chave não pode conter dois-pontos, vírgula ou quebra de linha.")
    configuration = json.loads(capture(compose("config", "--format", "json")))
    service = configuration["services"]["polaris-api"]
    if args.admin_user == service["environment"].get("TARGET_SSH_USER", "polaris"):
        raise ValueError("Use um usuário administrativo diferente do usuário de serviço.")
    volumes = [item for item in service.get("volumes", [])
               if item.get("target") == "/run/secrets/polaris_ssh_key"]
    if len(volumes) != 1 or volumes[0].get("type") != "bind":
        raise ValueError("Montagem da chave de serviço não foi identificada.")
    service_key = host_path(volumes[0]["source"])
    if not service_key.is_file():
        raise ValueError("Chave de serviço não encontrada no host.")
    if key == service_key or hashlib.sha256(key.read_bytes()).digest() == hashlib.sha256(service_key.read_bytes()).digest():
        raise ValueError("A chave administrativa deve ser distinta da chave de serviço.")
    return key


def validate_controlled_runtime():
    configuration = json.loads(capture(compose("config", "--format", "json")))
    for service in ("polaris-api", "polaris-reconciler"):
        fields = ["DB_HOST", "DB_PORT", "DB_USER", "DB_NAME_AUDIT", "POLARIS_CONFIDENCE_HISTORY"]
        if service == "polaris-api":
            fields += ["POLARIS_DEBUG", "TARGET_SSH_HOST", "TARGET_SSH_USER", "TARGET_SSH_KEY_PATH"]
        expression = f"import json,os; print(json.dumps({{k:os.environ.get(k) for k in {fields!r}}}))"
        actual = json.loads(capture(compose("exec", "-T", service, "python", "-c", expression)))
        expected = configuration["services"][service]["environment"]
        if any(str(actual.get(key)).lower() != str(expected.get(key)).lower() for key in fields):
            raise ValueError("Compose e serviços em execução divergem; recrie API/reconciler e confira o diagnóstico.")
        if str(actual.get("POLARIS_CONFIDENCE_HISTORY")).lower() != "false":
            raise ValueError("Desligue POLARIS_CONFIDENCE_HISTORY na API e no reconciler antes da rodada.")
        if service == "polaris-api" and str(actual.get("POLARIS_DEBUG")).lower() != "false":
            raise ValueError("Desligue POLARIS_DEBUG antes da rodada.")


@contextmanager
def image_overlay(image):
    # JSON is valid YAML; an overlay pins the immutable API image without retagging or rebuilding.
    with tempfile.TemporaryDirectory(prefix="polaris-lab-") as directory:
        path = Path(directory) / "compose.json"
        path.write_text(json.dumps({"services": {"polaris-api": {
            "image": image, "pull_policy": "never"}}}), encoding="utf-8")
        yield path


def temporary_command(overlay, module_args, mounts=()):
    command = compose("-f", str(overlay), "run", "--rm", "--no-deps", "-T",
                      "--pull", "never", "--user", "0:0", "--entrypoint", "python")
    for source, target, readonly in mounts:
        if any(char in str(source) for char in ":\n\r,"):
            raise ValueError("Caminho de montagem inválido.")
        command.extend(["--volume", f"{source}:{target}" + (":ro" if readonly else "")])
    return command + ["polaris-api", "-m", *module_args]


def module_arguments(args):
    action = args.action
    admin = ["--admin-user", args.admin_user, "--admin-key-file", ADMIN_MOUNT] if action in ADMIN_ACTIONS else []
    if action == "check":
        return ["experiment.scenarios.reset_environment", "--check", "--scenario", args.scenario, *admin]
    if action == "reset":
        return ["experiment.scenarios.reset_environment", "--reset-run-id", str(args.run_id), *admin]
    if action in {"prepare", "run"}:
        controller = (["experiment.scenarios.service_controller"] if args.scenario == "service_down"
                      else ["experiment.scenarios.resource_controller", args.scenario])
        command = [*controller, action, *admin]
        if action == "run":
            command += ["--arm", args.arm, "--repetition", str(args.repetition), "--operator", args.operator,
                        "--system-version", args.system_version, "--commit-sha", args.commit_sha,
                        "--timeout", str(args.timeout)]
        return command
    if action == "link":
        return ["experiment.rounds", "link", "--run-id", str(args.run_id),
                "--incident-id", str(args.incident_id), "--event-id", args.event_id]
    if action == "assess":
        return ["experiment.rounds", "assess", "--run-id", str(args.run_id),
                "--record-file", "/run/lab/assessment.json"]
    if action == "discard":
        return ["experiment.rounds", "discard", "--run-id", str(args.run_id), "--reason", args.reason]
    if action == "report":
        return ["experiment.analysis.report", "--output", "/lab-output/report",
                "--kind", args.kind, "--no-graphs"]
    raise ValueError("Operação não reconhecida.")


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Informe um inteiro positivo.")
    return number


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="action", required=True)
    admin = argparse.ArgumentParser(add_help=False)
    admin.add_argument("--admin-user", required=True)
    admin.add_argument("--admin-key-file", required=True)
    sub.add_parser("inspect", help="read-only Compose, revision, migration and diagnostic information")
    check = sub.add_parser("check", parents=[admin], help="read-only global checks, separated by 60s")
    check.add_argument("--scenario", choices=SCENARIOS, required=True)
    prepare = sub.add_parser("prepare", parents=[admin], help="create only the disposable disk fixture")
    prepare.add_argument("--scenario", choices=["disk_full"], required=True)
    run = sub.add_parser("run", parents=[admin], help="explicit injection and independent observation; no remedy")
    run.add_argument("--scenario", choices=SCENARIOS, required=True)
    run.add_argument("--arm", choices=["baseline", "hitl"], required=True)
    run.add_argument("--repetition", type=positive, required=True)
    run.add_argument("--operator", required=True)
    run.add_argument("--system-version", required=True)
    run.add_argument("--commit-sha", required=True)
    run.add_argument("--timeout", type=positive, required=True)
    link = sub.add_parser("link")
    link.add_argument("--run-id", type=positive, required=True)
    link.add_argument("--incident-id", type=positive, required=True)
    link.add_argument("--event-id", required=True)
    assess = sub.add_parser("assess")
    assess.add_argument("--run-id", type=positive, required=True)
    assess.add_argument("--record-file", required=True)
    discard = sub.add_parser("discard")
    discard.add_argument("--run-id", type=positive, required=True)
    discard.add_argument("--reason", required=True)
    reset = sub.add_parser("reset", parents=[admin])
    reset.add_argument("--run-id", type=positive, required=True)
    for action in ("backup", "report"):
        item = sub.add_parser(action)
        item.add_argument("--output", required=True, help="new host file (backup) or directory (report)")
        if action == "report":
            item.add_argument("--kind", choices=["synthetic", "collected"], required=True)
    return result


def backup(output):
    destination = host_path(output)
    partial = destination.with_name(destination.name + ".partial")
    if destination.exists() or partial.exists():
        raise ValueError("Backup ou arquivo parcial já existe; escolha outro nome.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = compose("exec", "-T", "polaris-db", "sh", "-c",
                      'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"')
    with partial.open("xb") as stream:
        os.chmod(partial, 0o600)
        code = subprocess.run(command, cwd=ROOT, stdout=stream, check=False).returncode
    if code:
        raise ValueError("Backup falhou; arquivo .partial preservado, não use como backup completo.")
    # Hard link refuses an output created by another writer while pg_dump was running.
    os.link(partial, destination)
    partial.unlink()
    print(f"Backup preservado: {destination}")
    return 0


def inspect_environment():
    image = running_image()
    print(json.dumps({"checkout_sha": capture(["git", "rev-parse", "HEAD"]), "api_image": image,
                      "tracked_changes": bool(capture(["git", "diff", "HEAD", "--name-only"]))}, ensure_ascii=False), flush=True)
    commands = [compose("ps"), compose("exec", "-T", "polaris-api", "python", "-m", "src.db.migrate", "--status"),
                compose("exec", "-T", "polaris-api", "python", "-c",
                        'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/api/v1/diagnostico", timeout=30).read().decode())')]
    for command in commands:
        code = subprocess.run(command, cwd=ROOT, check=False).returncode
        if code:
            return code
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == "inspect":
            return inspect_environment()
        if args.action == "backup":
            return backup(args.output)
        mounts = []
        if args.action in ADMIN_ACTIONS:
            mounts.append((validate_admin(args), ADMIN_MOUNT, True))
        if args.action == "run":
            validate_controlled_runtime()
            if not re.fullmatch(r"[0-9a-f]{40}", args.commit_sha):
                raise ValueError("Informe o SHA completo (40 caracteres hexadecimais minúsculos).")
            if capture(["git", "rev-parse", "HEAD"]) != args.commit_sha or capture(["git", "diff", "HEAD", "--name-only"]):
                raise ValueError("Checkout precisa estar limpo e corresponder ao SHA informado; confira também a imagem.")
        if args.action == "assess":
            record = host_path(args.record_file)
            if not record.is_file():
                raise ValueError("Arquivo de avaliação não encontrado no host.")
            mounts.append((record, "/run/lab/assessment.json", True))
        image = running_image()
        if args.action == "report":
            destination = host_path(args.output)
            if destination.exists():
                raise ValueError("Diretório do relatório já existe; escolha outro nome.")
            destination.mkdir(parents=True, mode=0o700)
            mounts.append((destination, "/lab-output", False))
            # Analysis is excluded from the API image; use the checked-out report code only here.
            mounts.append((ROOT / "experiment" / "analysis", "/app/experiment/analysis", True))
        with image_overlay(image) as overlay:
            code = subprocess.run(temporary_command(overlay, module_arguments(args), mounts), cwd=ROOT, check=False).returncode
        if args.action == "report":
            print(f"Saída no host: {destination / 'report'} (confira o código de saída).")
        return code
    except KeyboardInterrupt:
        print("Operação interrompida. Confira o ID da rodada e o alvo; nenhum reset foi solicitado.", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"Operação interrompida: {detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
