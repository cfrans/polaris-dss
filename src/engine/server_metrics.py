"""Read the configured server's resource samples without ingesting events or using SSH."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from .config import get_settings
from .zabbix_client import ZabbixClient


MAX_SAMPLE_AGE_SECONDS = 300
ITEM_KEYS = ("system.cpu.util[,idle]", "vm.memory.utilization", "vm.memory.size[pavailable]")


def read_sample(items: list[dict], key: str, now: datetime, *, invert: bool = False) -> dict | None:
    """Reject unsupported, duplicate, invalid or stale samples; never substitute zero."""
    matches = [item for item in items if item.get("key_") == key]
    if len(matches) != 1:
        return None
    item = matches[0]
    if str(item.get("state")) != "0" or str(item.get("status")) != "0":
        return None
    try:
        value = float(item["lastvalue"])
        clock = int(item["lastclock"])
        age = now.timestamp() - clock
        if not math.isfinite(value) or not 0 <= value <= 100 or clock <= 0 or not 0 <= age <= MAX_SAMPLE_AGE_SECONDS:
            return None
        collected = datetime.fromtimestamp(clock, tz=timezone.utc).isoformat()
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None
    return {"percentual": round(100 - value if invert else value, 1), "coletado_em": collected}


def get_server_metrics() -> dict[str, Any]:
    settings = get_settings()
    host_name = settings.polaris_zabbix_host.strip()
    now = datetime.now(timezone.utc)
    result = {"estado": "nao_configurado", "host": host_name or None,
              "fonte": "Zabbix", "verificado_em": now.isoformat(),
              "cpu": None, "memoria": None,
              "detalhe": "Configure o host do servidor no Polaris para consultar CPU e memória."}
    if not host_name or not settings.zabbix_url:
        return result
    if not (settings.zabbix_token or (settings.zabbix_user and settings.zabbix_password)):
        result.update(estado="indisponivel", detalhe="A consulta ao Zabbix precisa de credenciais válidas.")
        return result
    client = ZabbixClient(url=settings.zabbix_url, usuario=settings.zabbix_user,
                          senha=settings.zabbix_password, token=settings.zabbix_token, timeout=3)
    try:
        hosts = client._chamar("host.get", {"output": ["hostid", "host", "status"],
                                            "filter": {"host": [host_name]}, "limit": 2}) or []
        if len(hosts) != 1 or hosts[0].get("host") != host_name or str(hosts[0].get("status")) != "0":
            result.update(estado="indisponivel", detalhe="Host monitorado não encontrado ou desativado no Zabbix.")
            return result
        items = client._chamar("item.get", {
            "output": ["key_", "lastvalue", "lastclock", "state", "status"],
            "hostids": [hosts[0]["hostid"]], "filter": {"key_": list(ITEM_KEYS)},
        }) or []
        now = datetime.now(timezone.utc)
        result["verificado_em"] = now.isoformat()
        # A bare system.cpu.util agent key defaults to user CPU, not total busy CPU.
        # Explicit idle CPU avoids presenting that value as whole-server utilization.
        result["cpu"] = read_sample(items, "system.cpu.util[,idle]", now, invert=True)
        result["memoria"] = (read_sample(items, "vm.memory.utilization", now)
                             or read_sample(items, "vm.memory.size[pavailable]", now, invert=True))
        count = sum(result[key] is not None for key in ("cpu", "memoria"))
        result.update(estado="ok" if count == 2 else "parcial" if count else "sem_dados",
                      detalhe="Métricas do servidor consultadas pelo Zabbix." if count == 2 else
                      "Há métricas ausentes, inválidas ou sem coleta nos últimos cinco minutos.")
    except Exception:
        # Do not expose upstream response bodies, URLs with credentials or raw exceptions.
        result.update(estado="indisponivel", cpu=None, memoria=None,
                      detalhe="Não foi possível consultar as métricas no Zabbix.")
    return result
