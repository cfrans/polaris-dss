"""Bounded connection tests and in-memory SSH credentials for guided configuration."""
import base64
import hashlib
import io
import socket
import time

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def generate_key():
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                           serialization.PublicFormat.OpenSSH).decode()
    return private, public


def read_private_key(text):
    for key_type in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return key_type.from_private_key(io.StringIO(text))
        except (paramiko.SSHException, ValueError):
            continue
    raise ValueError("Chave de serviço inválida ou protegida por senha; use uma chave dedicada ao serviço.")


def inspect_host(host):
    with socket.create_connection((host, 22), timeout=4) as connection:
        with paramiko.Transport(connection) as transport:
            transport.banner_timeout = 4
            transport.start_client(timeout=4)
            key = transport.get_remote_server_key()
            return key, fingerprint(key)


def test_ssh(host, user, private, trusted_line, key_path=""):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    entry = paramiko.hostkeys.HostKeyEntry.from_line(trusted_line)
    if not entry or entry.key is None or host not in entry.hostnames:
        raise ValueError("Identidade SSH inválida.")
    client.get_host_keys().add(host, entry.key.get_name(), entry.key)
    try:
        client.connect(host, username=user, pkey=read_private_key(private) if private else None,
                       key_filename=key_path if not private else None, timeout=4, auth_timeout=4,
                       banner_timeout=4, allow_agent=False, look_for_keys=False)
        _, stdout, _ = client.exec_command("true", timeout=4)
        deadline = time.monotonic() + 4
        while not stdout.channel.exit_status_ready():
            if time.monotonic() >= deadline:
                raise TimeoutError("O alvo não concluiu o teste SSH no prazo.")
            time.sleep(0.05)
        if stdout.channel.recv_exit_status() != 0:
            raise ValueError("O teste SSH não foi concluído.")
    finally:
        client.close()
