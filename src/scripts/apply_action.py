"""Aplica somente a operação e a identidade do alvo aprovadas; nunca escolhe outro alvo."""
import base64
import datetime
import gzip
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time

MOUNT = "/mnt/polaris_test"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,100}\.log(?:\.gz)?$")


def same_file(current, target):
    return (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns,
            current.st_ctime_ns) == tuple(target[k] for k in
                                          ("dispositivo", "inode", "bytes", "mtime_ns", "ctime_ns"))


def inspect_open(path, own_descriptor=None):
    pids = [p for p in os.listdir("/proc") if p.isdigit()]
    if len(pids) > 512:
        raise ValueError("inspeção de descritores incompleta")
    for pid in pids:
        try:
            descriptors = os.listdir(f"/proc/{pid}/fd")
            if len(descriptors) > 256:
                raise ValueError("inspeção de descritores incompleta")
            for fd in descriptors:
                if int(pid) == os.getpid() and int(fd) == own_descriptor:
                    continue
                try:
                    if os.readlink(f"/proc/{pid}/fd/{fd}") == path:
                        raise ValueError("arquivo aberto por um processo")
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass


def apply_disk(operation, target):
    path = target["caminho"]
    name = os.path.basename(path)
    if (os.path.dirname(path) != MOUNT or not SAFE_NAME.fullmatch(name) or ".." in name
            or not os.path.ismount(MOUNT) or os.stat(MOUNT).st_dev == os.stat("/").st_dev):
        raise ValueError("arquivo/volume não autorizado")
    for directory in ("/mnt", MOUNT):
        s = os.lstat(directory)
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise ValueError("diretório não protegido")
    directory = os.open(MOUNT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = None
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as source:
            current = os.fstat(source.fileno())
            if (not stat.S_ISREG(current.st_mode) or current.st_uid != 0
                    or current.st_nlink != 1 or current.st_mode & 0o022
                    or not same_file(current, target)):
                raise ValueError("identidade do arquivo mudou; novo diagnóstico necessário")
            if operation == "remove":
                if not name.endswith(".log.gz") or time.time() - current.st_mtime < 7 * 86400:
                    raise ValueError("retenção mínima não atendida")
                inspect_open(path, source.fileno())
            elif operation == "compress":
                if not name.endswith(".log"):
                    raise ValueError("formato de log não permitido")
                inspect_open(path, source.fileno())
                vfs = os.fstatvfs(directory)
                if vfs.f_bavail * vfs.f_frsize <= current.st_size + 4096:
                    raise ValueError("espaço insuficiente para compressão segura")
                destination = name + ".gz"
                # Reserva um destino novo; recusa gzip existente em vez de sobrescrevê-lo.
                out = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=directory)
                temporary = destination
                with os.fdopen(out, "wb") as output:
                    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed:
                        while chunk := source.read(1024 * 1024):
                            compressed.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                inspect_open(path, source.fileno())
            else:
                raise ValueError("operação inválida")
            if not same_file(os.stat(name, dir_fd=directory, follow_symlinks=False), target):
                raise ValueError("arquivo mudou durante a operação")
            os.unlink(name, dir_fd=directory)
            temporary = None
            os.fsync(directory)
            print(f"{operation}: {path}")
    finally:
        if temporary:
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


def process_identity(pid):
    with open(f"/proc/{pid}/stat") as f:
        start = f.read().rsplit(")", 1)[1].split()[19]
    with open(f"/proc/{pid}/comm") as f:
        name = f.read().strip()
    return name, start


def apply_process(target):
    pid = target["pid"]
    if type(pid) is not int or pid <= 1 or target["nome"] not in ("stress-ng", "stress", "stress-ng-cpu"):
        raise ValueError("processo não autorizado")
    expected = (target["nome"], target["inicio"])
    # pidfd associa o sinal ao processo aberto e impede atingir um PID reutilizado.
    descriptor = os.pidfd_open(pid)
    try:
        if process_identity(pid) != expected:
            raise ValueError("identidade do processo mudou")
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        for _ in range(10):
            time.sleep(1)
            try:
                if process_identity(pid) != expected:
                    return
            except FileNotFoundError:
                return
        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        print(f"processo encerrado: {pid} {target['nome']}")
    finally:
        os.close(descriptor)


def apply_service(operation, target):
    if operation not in ("start", "restart") or target.get("servico") != "nginx":
        raise ValueError("serviço/operação não autorizado")
    state = subprocess.run(["/usr/bin/systemctl", "show", "nginx", "--property=ActiveState", "--value"],
                           capture_output=True, text=True, check=True, timeout=3).stdout.strip()
    if state != target["estado"] or state not in ("inactive", "failed"):
        raise ValueError("estado do serviço mudou; novo diagnóstico necessário")
    subprocess.run(["/usr/bin/systemctl", operation, "nginx"], check=True, timeout=30)


def apply(payload):
    stamp = datetime.datetime.fromisoformat(payload["coletado_em"])
    if stamp.utcoffset() is None or not 0 <= time.time() - stamp.timestamp() <= 300:
        raise ValueError("diagnóstico expirado")
    operation, target = payload["operacao"], payload["alvo"]
    if operation in ("compress", "remove"):
        apply_disk(operation, target)
    elif operation == "terminate":
        apply_process(target)
    elif operation in ("start", "restart"):
        apply_service(operation, target)
    else:
        raise ValueError("operação não autorizada")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or len(sys.argv[1]) > 8192:
            raise ValueError("plano ausente/inválido")
        apply(json.loads(base64.b64decode(sys.argv[1], altchars=b"-_", validate=True)))
    except Exception as error:
        print(f"operação recusada: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(2)
