"""Diagnóstico de conectividade e configuração.

Verifica, sob demanda, se o sistema alcança tudo de que depende: banco de auditoria, esquema
aplicado, base de conhecimento, API do Zabbix e host alvo por SSH. Cada verificação tem timeout
curto e devolve o mesmo formato, para que uma dependência lenta não trave a página inteira.

A configuração efetiva é devolvida junto, com os segredos **mascarados**: informa-se se um valor
está definido e o seu tamanho, nunca o valor. Uma tela de diagnóstico que exibe o token do webhook
resolve um problema e cria outro.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_settings

OK = "ok"
AVISO = "aviso"
FALHA = "falha"
NAO_CONFIGURADO = "nao_configurado"

# Toda variável cujo nome contenha um destes termos é exibida mascarada.
TERMOS_SENSIVEIS = ("password", "token", "secret", "key_path", "senha")


@dataclass(frozen=True, slots=True)
class Verificacao:
    id: str
    nome: str
    estado: str
    detalhe: str
    latencia_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "nome": self.nome, "estado": self.estado,
            "detalhe": self.detalhe, "latencia_ms": self.latencia_ms,
        }


@dataclass
class Diagnostico:
    verificacoes: list[Verificacao] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        contagem = {OK: 0, AVISO: 0, FALHA: 0, NAO_CONFIGURADO: 0}
        for v in self.verificacoes:
            contagem[v.estado] = contagem.get(v.estado, 0) + 1
        return {
            "verificacoes": [v.to_dict() for v in self.verificacoes],
            "configuracao": configuracao_efetiva(),
            "resumo": contagem,
        }


def _cronometrar(funcao) -> tuple[Verificacao, int]:
    inicio = time.perf_counter()
    resultado = funcao()
    return resultado, int((time.perf_counter() - inicio) * 1000)


def executar(kb=None) -> Diagnostico:
    """Roda todas as verificações. Nenhuma falha interrompe as demais."""
    d = Diagnostico()
    for funcao in (_verificar_banco, _verificar_migracoes,
                   lambda: _verificar_base_conhecimento(kb),
                   _verificar_zabbix, _verificar_alvo):
        try:
            verificacao, ms = _cronometrar(funcao)
        except Exception as exc:  # nenhuma verificação pode derrubar o diagnóstico
            verificacao, ms = Verificacao("desconhecida", "Verificação",
                                          FALHA, f"erro inesperado: {exc}"), None
        d.verificacoes.append(
            Verificacao(verificacao.id, verificacao.nome, verificacao.estado,
                        verificacao.detalhe, ms)
        )
    return d


# ---------------------------------------------------------------------------


def _verificar_banco() -> Verificacao:
    from ..db.connection import conectar

    try:
        with conectar(connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM audit_log")
                incidentes = cur.fetchone()["n"]
        s = get_settings()
        return Verificacao("banco", "Banco de auditoria", OK,
                           f"{s.db_name_audit} em {s.db_host}:{s.db_port} · "
                           f"{incidentes} incidente(s) registrado(s)")
    except Exception as exc:
        return Verificacao("banco", "Banco de auditoria", FALHA, _resumir(exc))


def _verificar_migracoes() -> Verificacao:
    """Compara as migrações em disco com as registradas no banco.

    Pendência aqui costuma significar que o container está rodando uma imagem anterior à migração
    criada — situação em que o aplicador responde que não há nada pendente, porque enxerga apenas
    os arquivos que estão dentro da imagem.
    """
    from ..db.connection import conectar
    from ..db.migrate import descobrir

    try:
        arquivos = descobrir()
        with conectar(connect_timeout=4) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT versao FROM schema_migrations")
                aplicadas = {linha["versao"] for linha in cur.fetchall()}
    except Exception as exc:
        return Verificacao("migracoes", "Esquema do banco", FALHA, _resumir(exc))

    pendentes = [m for m in arquivos if m.versao not in aplicadas]
    if pendentes:
        nomes = ", ".join(f"{m.versao}_{m.nome}" for m in pendentes)
        return Verificacao("migracoes", "Esquema do banco", FALHA,
                           f"{len(pendentes)} migração(ões) pendente(s): {nomes} — "
                           f"aplique com `python -m src.db.migrate`")
    return Verificacao("migracoes", "Esquema do banco", OK,
                       f"{len(arquivos)} migração(ões) aplicada(s)")


def _verificar_base_conhecimento(kb) -> Verificacao:
    from .knowledge_base import KnowledgeBaseError
    from .knowledge_base import load as carregar

    try:
        base = kb or carregar()
    except KnowledgeBaseError as exc:
        return Verificacao("base", "Base de conhecimento", FALHA, str(exc))

    habilitadas = len(base.habilitadas)
    total = len(base.regras)
    detalhe = f"v{base.versao_kb} · {habilitadas} de {total} regra(s) habilitada(s)"
    estado = OK if habilitadas else AVISO
    if not habilitadas:
        detalhe += " — nenhuma regra ativa, o sistema não reconhecerá incidente algum"
    return Verificacao("base", "Base de conhecimento", estado, detalhe)


def _verificar_zabbix() -> Verificacao:
    s = get_settings()
    if not s.zabbix_url:
        return Verificacao("zabbix", "API do Zabbix", NAO_CONFIGURADO,
                           "ZABBIX_URL não definida")

    from .zabbix_client import ZabbixClient, ZabbixError

    cliente = ZabbixClient(url=s.zabbix_url, usuario=s.zabbix_user,
                           senha=s.zabbix_password, token=s.zabbix_token, timeout=3)
    try:
        versao = cliente.versao()
    except ZabbixError as exc:
        return Verificacao("zabbix", "API do Zabbix", FALHA, _resumir(exc))

    if not (s.zabbix_token or (s.zabbix_user and s.zabbix_password)):
        return Verificacao("zabbix", "API do Zabbix", AVISO,
                           f"servidor responde (API {versao}), mas não há credenciais: "
                           f"a reconciliação não funcionará")
    try:
        cliente.autenticar()
    except ZabbixError as exc:
        return Verificacao("zabbix", "API do Zabbix", FALHA,
                           f"servidor responde (API {versao}), mas a autenticação falhou: "
                           f"{_resumir(exc)}")
    return Verificacao("zabbix", "API do Zabbix", OK, f"API {versao} · autenticação aceita")


def _verificar_alvo() -> Verificacao:
    s = get_settings()
    if not s.target_ssh_host:
        return Verificacao("alvo", "Host alvo (SSH)", NAO_CONFIGURADO,
                           "TARGET_SSH_HOST não definido — a remediação usará o executor simulado")
    if not s.target_ssh_key_path or not Path(s.target_ssh_key_path).exists():
        return Verificacao("alvo", "Host alvo (SSH)", FALHA,
                           f"chave não encontrada em {s.target_ssh_key_path or '(vazio)'}")

    try:
        from .remediation import runner_ssh

        codigo, _, erro = runner_ssh(
            s.target_ssh_host, s.target_ssh_user, s.target_ssh_key_path
        )("true", timeout=5)
    except Exception as exc:
        return Verificacao("alvo", "Host alvo (SSH)", FALHA,
                           f"{s.target_ssh_user}@{s.target_ssh_host}: {_resumir(exc)}")

    if codigo != 0:
        return Verificacao("alvo", "Host alvo (SSH)", FALHA,
                           f"conexão estabelecida, mas o comando de teste falhou: {erro.strip()}")
    return Verificacao("alvo", "Host alvo (SSH)", OK,
                       f"{s.target_ssh_user}@{s.target_ssh_host} responde")


# ---------------------------------------------------------------------------


def configuracao_efetiva() -> list[dict[str, Any]]:
    """Configuração em vigor, com segredos mascarados."""
    s = get_settings()
    itens: list[dict[str, Any]] = []
    for chave, valor in sorted(s.model_dump().items()):
        sensivel = any(termo in chave for termo in TERMOS_SENSIVEIS)
        itens.append({
            "chave": chave.upper(),
            "valor": _mascarar(valor) if sensivel else _apresentar(valor),
            "sensivel": sensivel,
            "definido": bool(str(valor).strip()),
        })
    return itens


def _mascarar(valor: Any) -> str:
    texto = str(valor).strip()
    if not texto:
        return "não definido"
    return f"definido ({len(texto)} caracteres)"


def _apresentar(valor: Any) -> str:
    texto = str(valor).strip()
    return texto if texto else "não definido"


def _resumir(exc: Exception) -> str:
    """Primeira linha da exceção. Rastreamento completo vai para o log, não para a tela."""
    return str(exc).strip().split("\n")[0][:200] or type(exc).__name__
