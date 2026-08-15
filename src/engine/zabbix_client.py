"""Integração com a camada de telemetria.

Duas responsabilidades separadas de propósito:

- `normalizar_webhook` é uma função pura que converte o corpo enviado pela *Action* do Zabbix no
  `Alert` interno. Não faz rede, e por isso é testável com payloads capturados.
- `ZabbixClient` fala JSON-RPC com o servidor, e serve ao laço de reconciliação que recupera
  eventos não entregues pelo webhook.

O caminho primário de ingestão é o webhook; o cliente é a rede de proteção.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from .models import Alert

# O Zabbix expõe a severidade ora como número, ora como rótulo, dependendo da macro usada.
SEVERIDADE_POR_CODIGO = {
    0: "baixa",    # Not classified
    1: "baixa",    # Information
    2: "media",    # Warning
    3: "alta",     # Average
    4: "alta",     # High
    5: "critica",  # Disaster
}
SEVERIDADE_POR_ROTULO = {
    "not classified": "baixa",
    "information": "baixa",
    "warning": "media",
    "average": "alta",
    "high": "alta",
    "disaster": "critica",
}

# Usado apenas quando o evento não traz a tag `polaris_tipo`. Classificar por prefixo de chave de
# item é heurística: funciona para os itens padrão do template Linux, mas a tag é o caminho correto
# porque deixa a classificação explícita no lado do Zabbix.
TIPO_POR_PREFIXO_ITEM = (
    ("vfs.fs.size", "disk_full"),
    ("vfs.fs.dependent.size", "disk_full"),
    ("system.cpu", "cpu_high"),
    ("proc.num", "service_down"),
    ("net.tcp.service", "service_down"),
    ("systemd.unit", "service_down"),
)

TAG_TIPO = "polaris_tipo"


class ZabbixError(RuntimeError):
    """Falha de comunicação ou de autenticação com a API do Zabbix."""


# ---------------------------------------------------------------------------
# Normalização do webhook
# ---------------------------------------------------------------------------


def normalizar_webhook(dados: dict[str, Any]) -> Alert:
    """Converte o corpo enviado pela Action do Zabbix no alerta interno.

    Campos ausentes viram `None` em vez de erro: um evento incompleto ainda pode casar com uma
    regra pelo texto, e recusá-lo perderia um incidente real.
    """
    tags = extrair_tags(dados.get("tags"))
    item_key = (dados.get("item_key") or "").strip()

    texto = " ".join(
        parte for parte in (dados.get("trigger"), dados.get("item_value"), dados.get("texto"))
        if parte
    ).strip()

    return Alert(
        tipo_alerta=classificar(tags, item_key),
        hostname=(dados.get("host") or "").strip(),
        texto=texto,
        valor=valor_numerico(dados.get("item_value")),
        metrica=item_key or None,
        severidade=traduzir_severidade(dados.get("severity")),
        id_evento=str(dados["event_id"]).strip() if dados.get("event_id") else None,
        ts_deteccao=interpretar_data(dados.get("event_time")),
    )


def extrair_tags(bruto: Any) -> dict[str, str]:
    """Aceita o dicionário do JSON-RPC ou a string da macro `{EVENT.TAGS}`.

    A macro entrega algo como `polaris_tipo: disk_full, scope: availability`.
    """
    if isinstance(bruto, dict):
        return {str(k).strip(): str(v).strip() for k, v in bruto.items()}
    if isinstance(bruto, list):
        return {str(t.get("tag", "")).strip(): str(t.get("value", "")).strip() for t in bruto}
    if isinstance(bruto, str):
        tags: dict[str, str] = {}
        for parte in bruto.split(","):
            if ":" in parte:
                chave, _, valor = parte.partition(":")
                tags[chave.strip()] = valor.strip()
        return tags
    return {}


def classificar(tags: dict[str, str], item_key: str) -> str:
    """Determina o tipo do alerta. A tag declarada no Zabbix tem precedência sobre a heurística."""
    if TAG_TIPO in tags and tags[TAG_TIPO]:
        return tags[TAG_TIPO]
    for prefixo, tipo in TIPO_POR_PREFIXO_ITEM:
        if item_key.startswith(prefixo):
            return tipo
    return "desconhecido"


def traduzir_severidade(bruto: Any) -> str | None:
    if bruto is None or bruto == "":
        return None
    if isinstance(bruto, int) or (isinstance(bruto, str) and bruto.strip().isdigit()):
        return SEVERIDADE_POR_CODIGO.get(int(bruto))
    return SEVERIDADE_POR_ROTULO.get(str(bruto).strip().lower())


def valor_numerico(bruto: Any) -> float | None:
    """Extrai o número de valores como `97.4 %`, `0`, `up (1)` ou `1.2 GB`."""
    if bruto is None:
        return None
    if isinstance(bruto, (int, float)):
        return float(bruto)
    achado = re.search(r"-?\d+(?:[.,]\d+)?", str(bruto))
    return float(achado.group(0).replace(",", ".")) if achado else None


def interpretar_data(bruto: Any) -> datetime | None:
    """Aceita epoch (`clock` do JSON-RPC) ou `AAAA.MM.DD HH:MM:SS` das macros de data e hora."""
    if bruto is None or bruto == "":
        return None
    if isinstance(bruto, (int, float)) or str(bruto).strip().isdigit():
        return datetime.fromtimestamp(int(bruto), tz=timezone.utc)
    texto = str(bruto).strip().replace("T", " ").replace("Z", "")
    for formato in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(texto, formato).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Cliente JSON-RPC
# ---------------------------------------------------------------------------


@dataclass
class ZabbixClient:
    url: str
    usuario: str = ""
    senha: str = ""
    token: str = ""
    timeout: float = 10.0
    _sessao: str = ""
    _seq: int = 0

    def _chamar(self, metodo: str, parametros: dict | list | None = None,
                autenticado: bool = True) -> Any:
        self._seq += 1
        corpo = {
            "jsonrpc": "2.0",
            "method": metodo,
            "params": parametros if parametros is not None else {},
            "id": self._seq,
        }
        cabecalhos = {"Content-Type": "application/json-rpc"}
        if autenticado:
            credencial = self.token or self._sessao
            if not credencial:
                credencial = self.autenticar()
            cabecalhos["Authorization"] = f"Bearer {credencial}"

        try:
            resposta = httpx.post(self.url, json=corpo, headers=cabecalhos, timeout=self.timeout)
            resposta.raise_for_status()
            dados = resposta.json()
        except httpx.HTTPError as exc:
            raise ZabbixError(f"falha ao chamar {metodo} em {self.url}: {exc}") from exc

        if "error" in dados:
            erro = dados["error"]
            raise ZabbixError(f"{metodo}: {erro.get('message')} {erro.get('data', '')}".strip())
        return dados.get("result")

    def versao(self) -> str:
        return self._chamar("apiinfo.version", autenticado=False)

    def autenticar(self) -> str:
        if self.token:
            return self.token
        if not (self.usuario and self.senha):
            raise ZabbixError("sem credenciais: defina ZABBIX_TOKEN ou ZABBIX_USER/ZABBIX_PASSWORD")
        self._sessao = self._chamar(
            "user.login", {"username": self.usuario, "password": self.senha}, autenticado=False
        )
        return self._sessao

    def problemas_abertos(self) -> list[dict[str, Any]]:
        """Problemas ainda em aberto, já enriquecidos com o host de origem.

        `problem.get` não devolve o host; a segunda chamada busca essa informação pelos ids de
        evento. São duas chamadas, e não uma, porque a alternativa seria adivinhar o host pelo
        texto do trigger.
        """
        problemas = self._chamar("problem.get", {
            "output": ["eventid", "name", "severity", "clock", "objectid"],
            "selectTags": ["tag", "value"],
            "recent": False,
            "sortfield": ["eventid"],
            "sortorder": "DESC",
            "limit": 200,
        }) or []
        if not problemas:
            return []

        eventos = self._chamar("event.get", {
            "eventids": [p["eventid"] for p in problemas],
            "output": ["eventid"],
            "selectHosts": ["host"],
        }) or []
        host_por_evento = {
            e["eventid"]: (e.get("hosts") or [{}])[0].get("host", "") for e in eventos
        }

        for p in problemas:
            p["host"] = host_por_evento.get(p["eventid"], "")
        return problemas

    def alertas_abertos(self) -> list[Alert]:
        """Problemas em aberto já convertidos para o formato interno."""
        return [
            normalizar_webhook({
                "event_id": p["eventid"],
                "host": p.get("host", ""),
                "trigger": p.get("name", ""),
                "severity": p.get("severity"),
                "event_time": p.get("clock"),
                "tags": p.get("tags", []),
            })
            for p in self.problemas_abertos()
        ]
