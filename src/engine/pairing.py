"""Optional browser pairing for plain HTTP inside an isolated laboratory network.

Disabled by default (``POLARIS_PAREAMENTO_HTTP=false``). When enabled, a browser reaching the
server by a non-loopback HTTP address must first redeem a short code issued on the server
terminal. The code is single-use and short-lived; the browser then keeps its own random token.

Pairing proves that someone with shell access to the server allowed that browser. It does not
encrypt traffic: passwords, session cookies and secrets typed in the browser still travel in clear
text over HTTP. It never replaces account login, sessions or the persisted human approval.

    docker compose exec polaris-api python -m src.engine.pairing --address 192.0.2.10
"""
from __future__ import annotations

import hashlib
import secrets

from ..db.connection import conectar

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_MINUTES = 10
PAIRING_DAYS = 7
COOKIE = "polaris_pairing"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
DOCS_URL = "https://github.com/cfrans/polaris-dss/blob/main/docs/access.md#network-access"


def normalize(code: str) -> str:
    return "".join(char for char in str(code).upper() if char.isalnum())


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def issue_code() -> str:
    """Create a single-use code; expired codes and pairings are discarded first."""
    code = new_code()
    with conectar() as conn:
        conn.execute("DELETE FROM pareamentos WHERE (token_hash IS NULL AND ts_expiracao_codigo < now())"
                     " OR ts_expiracao < now()")
        conn.execute("INSERT INTO pareamentos(codigo_hash, ts_expiracao_codigo)"
                     " VALUES (%s, now() + make_interval(mins => %s))",
                     (digest(normalize(code)), CODE_MINUTES))
        conn.commit()
    return code


def redeem(conn, code: str, origin: str) -> str | None:
    """Consume a valid code atomically and return the browser token, or None."""
    normalized = normalize(code)
    if len(normalized) != CODE_LENGTH:
        return None
    token = secrets.token_urlsafe(32)
    row = conn.execute("""UPDATE pareamentos SET token_hash=%s, ts_pareamento=now(),
        ts_expiracao=now() + make_interval(days => %s), origem=%s
        WHERE codigo_hash=%s AND token_hash IS NULL AND ts_expiracao_codigo > now()
        RETURNING id""", (digest(token), PAIRING_DAYS, (origin or "")[:64], digest(normalized))).fetchone()
    conn.commit()
    return token if row else None


def is_paired(token: str) -> bool:
    if not token or len(token) > 128:
        return False
    with conectar() as conn:
        row = conn.execute("SELECT 1 FROM pareamentos WHERE token_hash=%s AND ts_expiracao > now()",
                           (digest(token),)).fetchone()
    return row is not None


def revoke_all() -> int:
    with conectar() as conn:
        count = conn.execute("DELETE FROM pareamentos RETURNING id").rowcount
        conn.commit()
    return count


def is_local(request) -> bool:
    return request.url.scheme == "https" or request.url.hostname in LOOPBACK


def transport_state(request, enabled: bool) -> str:
    """secure (HTTPS/loopback), paired, required (pairing pending) or blocked."""
    if is_local(request):
        return "secure"
    if not enabled:
        return "blocked"
    return "paired" if is_paired(request.cookies.get(COOKIE, "")) else "required"


def access_instructions(port: int, enabled: bool, address: str = "", ssh_user: str = "",
                        code: str = "") -> list[str]:
    """Lines printed by the server commands; the container cannot discover the host address."""
    host = address or "<IP-do-servidor>"
    account = ssh_user or "<usuario>"
    lines = ["Continue pelo navegador.",
             f"  No próprio servidor: http://localhost:{port}/login.html"]
    if enabled and code:
        lines += [f"  Em outro computador da rede: http://{host}:{port}/login.html",
                  f"  Código de pareamento (uso único, vale {CODE_MINUTES} minutos): {code}",
                  "  Atenção: por HTTP, senhas e sessão trafegam sem criptografia.",
                  "  Use o pareamento somente em uma rede de laboratório isolada."]
    elif enabled:
        lines += [f"  Em outro computador da rede: http://{host}:{port}/login.html",
                  "  Gere um código de pareamento: python -m src.engine.pairing"]
    else:
        lines += ["  Em outro computador, abra um túnel SSH e mantenha-o aberto:",
                  f"    ssh -N -L 8000:localhost:{port} {account}@{host}",
                  "  Depois acesse http://localhost:8000/login.html nesse computador.",
                  "  Para parear pela rede sem túnel, veja POLARIS_PAREAMENTO_HTTP em:",
                  f"  {DOCS_URL}"]
    if not address:
        lines.append("  Informe --address com o IP do servidor para completar os endereços acima.")
    return lines


def main():
    import argparse
    from .config import get_environment_settings
    parser = argparse.ArgumentParser(description="Gera um código de pareamento de navegador ou mostra o túnel SSH.")
    parser.add_argument("--address", default="", help="IP ou nome do servidor visto pelos outros computadores")
    parser.add_argument("--ssh-user", default="", help="usuário SSH do servidor, usado no comando do túnel")
    parser.add_argument("--revoke", action="store_true", help="revoga todos os navegadores pareados e códigos pendentes")
    args = parser.parse_args()
    settings = get_environment_settings()
    if args.revoke:
        print(f"Pareamentos revogados: {revoke_all()}. Navegadores precisarão de um novo código.")
        return
    code = ""
    if settings.polaris_pareamento_http:
        try:
            code = issue_code()
        except Exception:
            raise SystemExit("Não foi possível gerar o código. Confira o banco e as migrações.") from None
    else:
        print("Pareamento por HTTP desativado (POLARIS_PAREAMENTO_HTTP=false).")
    print("\n".join(access_instructions(settings.polaris_api_port, settings.polaris_pareamento_http,
                                        args.address, args.ssh_user, code)))


if __name__ == "__main__":
    main()
