"""Coleta limitada de metadados e padrões conhecidos; não altera arquivos ou serviços."""
import datetime
import json
import os
import pwd
import re
import selectors
import stat
import subprocess
import sys
import time

MOUNT = "/mnt/polaris_test"


def command(args):
    # Limita bytes durante a leitura, não depois de acumular um log arbitrariamente grande.
    data = bytearray()
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 3
            while len(data) < 16384 and time.monotonic() < deadline:
                if selector.select(.1):
                    chunk = os.read(process.stdout.fileno(), min(4096, 16384 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)
    return data.decode("utf-8", "replace")


def open_files():
    found = set()
    complete = True
    pids = [p for p in os.listdir("/proc") if p.isdigit()]
    if len(pids) > 512:
        return found, False
    for pid in pids:
        try:
            descriptors = os.listdir(f"/proc/{pid}/fd")
            if len(descriptors) > 256:
                complete = False
            for fd in descriptors[:256]:
                try:
                    found.add(os.readlink(f"/proc/{pid}/fd/{fd}"))
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
        except PermissionError:
            complete = False
    return found, complete


def disk():
    if not os.path.ismount(MOUNT) or os.stat(MOUNT).st_dev == os.stat("/").st_dev:
        raise ValueError("volume não isolado")
    mount = os.lstat(MOUNT)
    if mount.st_uid != 0 or mount.st_mode & 0o022:
        raise ValueError("volume gravável por terceiros")
    opened, complete = open_files()
    files = []
    with os.scandir(MOUNT) as scan:
        for index, entry in enumerate(scan):
            if index >= 256:
                complete = False
                break
            s = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(s.st_mode) or not entry.name.endswith((".log", ".log.gz")):
                continue
            files.append({"caminho": entry.path, "bytes": s.st_size, "mtime_ns": s.st_mtime_ns,
                          "ctime_ns": s.st_ctime_ns, "inode": s.st_ino, "dispositivo": s.st_dev,
                          "uid": s.st_uid, "modo": stat.S_IMODE(s.st_mode), "links": s.st_nlink,
                          "idade_s": max(0, time.time() - s.st_mtime),
                          "proprietario": pwd.getpwuid(s.st_uid).pw_name,
                          "aberto": entry.path in opened if complete else None})
    vfs = os.statvfs(MOUNT)
    return {"arquivos": files, "completo": complete,
            "espaco_livre": vfs.f_bavail * vfs.f_frsize}


def service():
    state = command(["/usr/bin/systemctl", "show", "nginx", "--property=ActiveState", "--value"]).strip()
    # Somente propriedades fixas; não exportar journal bruto ou atribuir causa ao estado.
    properties = command(["/usr/bin/systemctl", "show", "nginx",
                          "--property=Result,ExecMainCode,ExecMainStatus,InactiveEnterTimestamp"])
    fields = dict(line.split("=", 1) for line in properties.splitlines() if "=" in line)
    exit_info = {"resultado": fields.get("Result"), "tipo": fields.get("ExecMainCode"),
                 "codigo": fields.get("ExecMainStatus"),
                 "inativo_em": fields.get("InactiveEnterTimestamp")}
    sources = [("journal:nginx", command(["/usr/bin/journalctl", "-u", "nginx", "-n", "40",
                                         "--since", "-15min", "--no-pager", "-o", "cat"]))]
    try:
        fd = os.open("/var/log/nginx/error.log", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise ValueError("log não regular")
            f.seek(max(0, os.fstat(f.fileno()).st_size - 16384))
            sources.append(("nginx/error.log", f.read(16384).decode("utf-8", "replace")))
    except (FileNotFoundError, PermissionError):
        pass
    findings = []
    for source, text in sources:
        for code, pattern in [("porta", r"address already in use"),
                              ("configuracao", r"invalid (?:parameter|number of arguments)|unknown directive|syntax error"),
                              ("permissao", r"permission denied")]:
            match = re.search(pattern, text, re.I)
            if match:
                # Exporta somente o padrão reconhecido, nunca linhas com URLs, tokens ou credenciais.
                findings.append({"codigo": code, "fonte": source, "trecho": match.group(0)})
    return {"estado_servico": state, "saida_servico": exit_info, "indicios": findings,
            "limite": "40 mensagens do journal em 15 min e últimos 16 KiB do error.log; indícios não comprovam causa-raiz."}


def cpu():
    pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
    if len(pids) > 512:
        return {"processo": None, "completo": False}
    def sample(pid):
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return int(fields[11]) + int(fields[12]), fields[19]
    initial = {}
    for pid in pids:
        try:
            initial[pid] = sample(pid)
        except (FileNotFoundError, ProcessLookupError):
            pass
    start = time.monotonic()
    time.sleep(1)
    elapsed = time.monotonic() - start
    candidates = []
    for pid, (ticks, identity) in initial.items():
        try:
            current, new_identity = sample(pid)
            if identity == new_identity and current > ticks:
                with open(f"/proc/{pid}/comm") as f:
                    name = f.read().strip()
                candidates.append({"pid": pid, "nome": name, "inicio": identity,
                                   "cpu_pct": round((current - ticks) / os.sysconf("SC_CLK_TCK") / elapsed * 100, 2)})
        except (FileNotFoundError, ProcessLookupError):
            pass
    return {"processo": max(candidates, key=lambda p: (p["cpu_pct"], -p["pid"])) if candidates else None,
            "fonte": "Diferença de tempo de CPU de /proc em amostra de um segundo; até 512 processos."}


if __name__ == "__main__":
    try:
        kind = sys.argv[1]
        data = {"disk_full": disk, "service_down": service, "cpu_high": cpu}[kind]()
        print(json.dumps({"tipo": kind,
                          "coletado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(), **data}))
    except Exception:
        print(json.dumps({"tipo": sys.argv[1] if len(sys.argv) > 1 else "", "erro": "Coleta indisponível ou incompleta."}))
        sys.exit(2)
