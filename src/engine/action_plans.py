"""Planos determinísticos: evidência de leitura, opções fixas e aprovação específica."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone

from .config import get_settings
from .models import Alert, Suggestion

PLAN_RULES = {"R001", "R002", "R003"}
MAX_PLAN_AGE = 300
SAFE_LOG = re.compile(r"^/mnt/polaris_test/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,100}\.log(?:\.gz)?$")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def collect_evidence(alert: Alert, catalog=None):
    settings = get_settings()
    if not settings.target_ssh_host:
        return None
    if not settings.target_ssh_key_path:
        return {"erro": "Chave de serviço não configurada; diagnóstico indisponível."}
    if not alert.ip_address or alert.ip_address != settings.target_ssh_host:
        return {"erro": "O IP do alerta não coincide com o alvo SSH autorizado."}
    if alert.tipo_alerta not in ("disk_full", "cpu_high", "service_down"):
        return None
    from .remediation import runner_ssh
    from .script_catalog import load_catalog
    catalog = catalog or load_catalog()
    try:
        runner = runner_ssh(settings.target_ssh_host, settings.target_ssh_user,
                            settings.target_ssh_key_path)
        # O comando é fixo; apenas um seletor de enumeração validada é acrescentado.
        command = ("sudo -n /usr/bin/timeout -k 2s 8s /usr/bin/python3 - "
                   + alert.tipo_alerta)
        code, output, _ = runner(command, timeout=10,
                                  input_data=catalog.get("collect_evidence.py").content)
        if code or len(output) > 32768:
            raise ValueError("coleta incompleta")
        result = json.loads(output)
        if not isinstance(result, dict) or result.get("tipo") != alert.tipo_alerta:
            raise ValueError("resposta inválida")
        result["catalogo_sha256"] = catalog.sha256
        return result
    except Exception:
        return {"erro": "Diagnóstico remoto indisponível; investigação manual necessária."}


def build_plan(suggestion: Suggestion, evidence: dict, preferences=None, choices=None,
               history_enabled=False, config=None, outcomes=None):
    plan = {"schema": 1, "regra": suggestion.rule.id,
            "estado": evidence.get("estado", "concluido"),
            "versao_scripts": evidence.get("catalogo_sha256"),
            "regra_sha256": digest(asdict(suggestion.rule)),
            "versao_kb": suggestion.trace.versao_kb,
            "coletado_em": evidence.get("coletado_em", datetime.now(timezone.utc).isoformat()),
            "evidencias": evidence, "opcoes": [],
            "aviso": "Confiança é um índice de evidências, não uma probabilidade de sucesso."}
    options = plan["opcoes"]

    def add(operation, target, title, reason, destructive=False):
        payload = {"operacao": operation, "alvo": target, "coletado_em": plan["coletado_em"]}
        encoded = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
        options.append({"id": digest(payload), "operacao": operation, "titulo": title,
                        "motivo": reason, "alvo": target,
                        "comando": "apply_action.py " + encoded,
                        "confianca": suggestion.confianca, "banda": suggestion.banda.value,
                        "destrutiva": destructive,
                        "timeout_segundos": suggestion.rule.remediacao.timeout_segundos,
                        "rollback": ("Exclusão irreversível; recuperação depende de backup."
                                     if operation == "remove" else
                                     "Descompressão manual requer espaço e destino livre; o conteúdo permanece no gzip."
                                     if operation == "compress" else suggestion.rollback)})

    if evidence.get("erro"):
        plan["aviso"] = evidence["erro"]
    elif suggestion.rule.id == "R001":
        files = evidence.get("arquivos", [])
        for f in sorted(files, key=lambda f: f.get("mtime_ns", 0)):
            path = f.get("caminho", "")
            if (not SAFE_LOG.fullmatch(path) or ".." in path or f.get("uid") != 0
                    or f.get("links") != 1 or f.get("modo", 0) & 0o022):
                continue
            if (path.endswith(".log.gz") and f.get("idade_s", 0) >= 7 * 86400
                    and f.get("aberto") is False):
                add("remove", f, "Remover log comprimido antigo",
                    "Arquivo regular de root; retenção mínima de sete dias. Confira a necessidade antes de aprovar.", True)
            elif (path.endswith(".log") and f.get("aberto") is False
                  and evidence.get("espaco_livre", 0) > f.get("bytes", 0) + 4096):
                add("compress", f, "Comprimir log fechado",
                    "Log sem descritor aberto observado; compressão individual com espaço temporário suficiente.", True)
            if len(options) >= 5:
                break
    elif suggestion.rule.id == "R003":
        state = evidence.get("estado_servico")
        if evidence.get("indicios"):
            plan["aviso"] = "Há indícios de configuração, porta ou permissão; investigar antes de reiniciar."
        elif state in ("inactive", "failed"):
            target = {"servico": "nginx", "estado": state}
            if state == "inactive":
                add("start", target, "Iniciar nginx", "O serviço está inativo; iniciar sem parar uma instância ativa.")
            add("restart", target, "Reiniciar nginx", "Reinício explícito do serviço nginx e verificação posterior de saúde.")
    elif suggestion.rule.id == "R002":
        process = evidence.get("processo")
        if (process and process.get("nome") in suggestion.rule.condicao.processos_alvo_permitidos
                and process.get("cpu_pct", 0) >= (suggestion.rule.condicao.limiar_uso_pct or 90)):
            add("terminate", process, "Encerrar o processo identificado",
                "SIGTERM para o PID mostrado; SIGKILL após dez segundos somente se a identidade persistir.", True)
    if not options:
        plan["aviso"] += " Nenhuma ação automática segura oferecida; investigação manual necessária."
    preferences = preferences or {"modo_preferencia": "desempate", "desconto_maximo": 0.10,
                                  "minimo_escolhas": 5, "versao": 1}
    plan["preferencias"] = preferences
    plan["historico_habilitado"] = history_enabled
    choices = choices or {}
    total = sum(choices.values())
    enough = history_enabled and total >= preferences["minimo_escolhas"]
    for option in options:
        cfg = config or {}
        f3 = cfg.get("F3", {"n_minimo": 5, "taxa_boa": .9, "taxa_regular": .7,
                            "mult_boa": 1., "mult_regular": .9, "mult_ruim": .75})
        outcome = (outcomes or {}).get(option["operacao"], {"n": 0, "sucessos": 0})
        technical_factor = 1.
        if history_enabled and outcome["n"] >= f3["n_minimo"]:
            rate = outcome["sucessos"] / outcome["n"]
            technical_factor = (f3["mult_boa"] if rate >= f3["taxa_boa"] else
                                f3["mult_regular"] if rate >= f3["taxa_regular"] else f3["mult_ruim"])
        # Para opções do mesmo incidente, F3 passa a refletir o resultado daquela operação;
        # não penalizar todas as alternativas novamente pelo F3 agregado da regra.
        previous_f3 = next((f.valor for f in suggestion.trace.fatores if f.id == "F3"), 1.)
        option["confianca"] = round(option["confianca"] / previous_f3 * technical_factor, 4)
        option["historico_acao"] = {**outcome, "fator": technical_factor,
                                    "habilitado": history_enabled}
        count = choices.get(option["operacao"], 0) if history_enabled else 0
        factor = 1.0
        if enough and preferences["modo_preferencia"] == "desconto":
            factor -= preferences["desconto_maximo"] * (1 - count / max(choices.values()))
        option["confianca_tecnica"] = option["confianca"]
        option["confianca"] = round(option["confianca"] * factor, 4)
        bands = (config or {}).get("bandas", {"alta": 0.90, "media": 0.70})
        option["banda"] = ("alta" if option["confianca"] >= bands["alta"] else
                           "media" if option["confianca"] >= bands["media"] else "baixa")
        option["preferencia"] = {"escolhas": count, "total": total if history_enabled else 0,
                                 "fator": factor, "modo": preferences["modo_preferencia"],
                                 "aplicada": enough and preferences["modo_preferencia"] != "desligado"}
    options.sort(key=lambda a: (-a["confianca"],
                 -a["preferencia"]["escolhas"] if enough and preferences["modo_preferencia"] == "desempate" else 0))
    plan["versao"] = digest(plan)
    return plan


def verify_plan(plan):
    body = {key: value for key, value in plan.items() if key != "versao"}
    if plan.get("versao") != digest(body):
        raise ValueError("Plano de ação foi alterado.")


def choose_action(plan, version, option_id, *, check_age=True):
    verify_plan(plan)
    if version != plan["versao"]:
        raise ValueError("O diagnóstico mudou. Revise o plano antes de aprovar.")
    if check_age:
        created = datetime.fromisoformat(plan["coletado_em"])
        if created.utcoffset() is None or not 0 <= time.time() - created.timestamp() <= MAX_PLAN_AGE:
            raise ValueError("Diagnóstico expirado. Atualize-o antes de aprovar.")
    option = next((a for a in plan["opcoes"] if a["id"] == option_id), None)
    if option is None:
        raise ValueError("Ação não oferecida neste diagnóstico.")
    return option
