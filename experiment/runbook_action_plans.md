# Manual baseline with specific targets

> **Decision of 2026-10-17 (rehearsal 15):** the baseline arm is the operator's usual manual
> procedure: read the alert in Zabbix, connect through the bastion to the target and use ordinary
> administration commands (for nginx, `systemctl status` and `systemctl start`/`restart`). The
> operator does not run the Polaris collector or executor below; those bytes stay a reference for
> the policy limits only. The policy below still bounds what a correct manual remedy may change
> (which file, which process), and every command and navigation still counts as a step.
>
> The operator procedures live in [the operator knowledge base](kb_operador/README.md): R001 and
> R002 are executed from the KB, with commands copied; R003 is typed from memory. Opening or
> scrolling the KB counts as a navigation step; web search and AI assistance are not used.

Use this procedure with KB 1.0.2. It supersedes blanket disk cleanup and late CPU candidate
selection in the earlier runbooks. Rehearse it before official collection. It changes neither
the independent observer nor the alert-driven operator start and actual-action counting.

Before injection, keep a separate operator terminal in the frozen source checkout on the Linux
server, with the established administrative SSH key and host trust. No target SSH session is
already open. Prepare a fresh evidence directory before the measured task:

```bash
BASELINE_EVIDENCE=$(mktemp -d experiment/evidence/manual-XXXXXX)
set -o noclobber
```

After the real Zabbix alert, identify the target/scenario. Start only then; controller output
is not a detection signal. Each submitted command, new SSH session and diagnostic navigation
counts under the operational definition, including retries. Instrumentation commands do not.

## 1. Inspect, without requesting a recommendation

Example for disk pressure, using the same frozen read-only bytes as HITL:

```bash
ssh -i ~/.ssh/id_ed25519 root@192.168.0.152 '/usr/bin/timeout -k 2s 8s /usr/bin/python3 - disk_full' < src/scripts/collect_evidence.py > "$BASELINE_EVIDENCE/diagnostico.json"
python3 -m json.tool "$BASELINE_EVIDENCE/diagnostico.json"
```

For CPU or nginx use the fixed selector `cpu_high` or `service_down` instead. This explicit manual
invocation collects metadata only; it does not rank, select, approve or execute a remedy.
The operator reads the evidence and decides. An incomplete inspection needs investigation.

## 2. Choose the applicable operation and target manually

Disk policy: only the isolated `/mnt/polaris_test`, regular root-owned `.log`/`.log.gz`, no
symlink/hard-link ambiguity or group/world write permissions, no open descriptor. Removal requires
at least seven days of retention and human confirmation that the file is disposable. Compression
requires a closed `.log`, enough free temporary space, and a new gzip destination. No global rotation.

CPU policy: the highest sampled consumer must be on the frozen allowlist and use at least 50% of one CPU.
Confirm the displayed PID/name. Nginx policy: inspect the fixed log clues; known configuration,
permission or port errors require investigation. Only start/restart in the displayed applicable state.
Record a valid failure honestly; do not use instrumentation reset as manual remediation.

Create an exact payload from the collected identity. This example explicitly chooses `remove`
and a human-selected file; substitute the actual observed path. It does not select another file:

```bash
PLAN_PAYLOAD=$(python3 - "$BASELINE_EVIDENCE/diagnostico.json" remove /mnt/polaris_test/polaris_r001_lab.log.gz <<'PY'
import base64,json,sys
with open(sys.argv[1]) as stream:
    evidence=json.load(stream)
operation,selected=sys.argv[2:]
if operation in ('remove','compress'):
    target=next(f for f in evidence['arquivos'] if f['caminho']==selected)
elif operation=='terminate':
    target=evidence['processo']
    assert target and str(target['pid'])==selected
elif operation in ('start','restart'):
    assert selected=='nginx'
    target={'servico':'nginx','estado':evidence['estado_servico']}
else:
    raise ValueError('operation not permitted')
payload={'operacao':operation,'alvo':target,'coletado_em':evidence['coletado_em']}
print(base64.urlsafe_b64encode(json.dumps(payload,sort_keys=True).encode()).decode())
PY
)
```

For compression choose `compress` and the exact `.log` path; for CPU choose `terminate` and
the exact PID; for nginx choose `start` or `restart` and `nginx`. Use the actual scenario's
timeout (disk 60 s, CPU 45 s, nginx 120 s). After choosing, dispatch the frozen executor bytes:

```bash
ssh -i ~/.ssh/id_ed25519 root@192.168.0.152 "/usr/bin/timeout -k 5s 60s /usr/bin/python3 - '$PLAN_PAYLOAD'" < src/scripts/apply_action.py
```

The payload is base64 JSON produced above, not arbitrary shell text. The script rechecks the
five-minute validity and exact target identity. Refusal requires inspection and a new snapshot;
it never switches targets. This is explicit administrative manual operation, separate from the
Polaris application executor and its persisted-approval invariant.

## 3. Confirm and preserve

Confirm resource/service health and inspect collateral effects. The independent observer defines
t5. Record actual steps, literal commands, correctness and missing measurements. Preserve the
diagnostic snapshot, video, round backup and report before explicit assessment/discard/reset.
HITL follows the same policy and effects, with automatic inspection and human option approval;
do not invoke this manual dispatch from the HITL arm.
