"""Authenticated local configuration storage, independent of the audit database."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile

from cryptography.fernet import Fernet, InvalidToken


class VaultError(RuntimeError):
    pass


class Vault:
    def __init__(self, directory: str | Path, key_file: str | Path):
        root = Path(__file__).resolve().parents[2]
        self.directory = (root / Path(directory)).resolve()
        self.key_file = (root / Path(key_file)).resolve()
        self.path = self.directory / "configuration.enc"
        if self.key_file.resolve().is_relative_to(self.directory.resolve()):
            raise VaultError("A chave mestra deve ficar fora do diretório do arquivo cifrado.")

    def read(self):
        if not self.path.exists():
            return {}
        try:
            data = Fernet(self.key_file.read_bytes()).decrypt(self.path.read_bytes())
            result = json.loads(data)
            if result.get("schema") != 1 or not isinstance(result.get("settings"), dict):
                raise ValueError("schema")
            return result
        except (OSError, ValueError, InvalidToken, TypeError):
            raise VaultError("Não foi possível abrir o cofre. Confira sua chave e o backup; nada foi substituído.") from None

    @contextmanager
    def locked(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(self.directory / "configuration.lock", "a+b") as handle:
            if os.name == "nt":
                import msvcrt
                if not handle.tell():
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def update(self, change, revision=None):
        with self.locked():
            data = self.read()
            if not data:
                raise VaultError("Inicialize o acesso administrativo pelo terminal do servidor.")
            if revision is not None and data.get("revision") != revision:
                raise VaultError("A configuração mudou. Carregue e teste novamente.")
            change(data)
            data["revision"] = secrets.token_hex(16)
            self._write(data)
            return data

    def _write(self, data):
        encrypted = Fernet(self.key_file.read_bytes()).encrypt(json.dumps(data).encode())
        descriptor, temporary = tempfile.mkstemp(dir=self.directory, prefix=".configuration-")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def initialize(self):
        with self.locked():
            if self.path.exists():
                raise VaultError("Acesso já inicializado. O cofre existente foi preservado.")
            self.key_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not self.key_file.exists():
                descriptor = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(Fernet.generate_key())
            code = secrets.token_urlsafe(32)
            self._write({"schema": 1, "settings": {}, "revision": secrets.token_hex(16),
                         "access_hash": hashlib.sha256(code.encode()).hexdigest()})
            (self.directory / "operations.lock").touch(mode=0o600, exist_ok=True)
            return code


def configured_vault(settings):
    if not settings.polaris_setup_dir:
        return None
    if not settings.polaris_setup_key_file:
        raise VaultError("Configure o arquivo externo da chave mestra.")
    return Vault(settings.polaris_setup_dir, settings.polaris_setup_key_file)


@contextmanager
def operation_guard(vault, exclusive=False):
    """Serialize configuration changes against API traffic and reconciler cycles."""
    path = vault.directory / "operations.lock" if vault else None
    if path is None or not path.exists():
        yield
        return
    with path.open("rb") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            raise VaultError("Há uma operação em andamento. Aguarde e tente novamente.") from None
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def main():
    import argparse
    from .config import get_environment_settings
    parser = argparse.ArgumentParser(description="Inicializa o cofre ou troca seu código administrativo local.")
    parser.add_argument("--rotate-access", action="store_true", help="troca o código e invalida sessões, preservando configurações")
    args = parser.parse_args()
    vault = configured_vault(get_environment_settings())
    if vault is None:
        raise SystemExit("Habilite os volumes de configuração e chave antes de inicializar.")
    try:
        if args.rotate_access:
            code = secrets.token_urlsafe(32)
            vault.update(lambda data: data.update(access_hash=hashlib.sha256(code.encode()).hexdigest()))
        else:
            code = vault.initialize()
    except VaultError as exc:
        raise SystemExit(str(exc)) from None
    print("Guarde este código administrativo em um gerenciador de senhas. Ele não será exibido novamente.")
    print(code)


if __name__ == "__main__":
    main()
