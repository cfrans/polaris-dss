#!/usr/bin/env bash
# Explicit R002 instrumentation in one dedicated, non-restarting transient service.
set -euo pipefail
[[ $# == 1 ]] || { echo 'expected check, inject or reset' >&2; exit 2; }
action=$1
case "$action" in check|inject|reset) ;; *) exit 2 ;; esac
[[ "$(id -u)" == 0 ]] || { echo 'administrative privileges required' >&2; exit 3; }
unit=polaris-experiment-cpu.service
marker='Polaris R002 experiment instrumentation'
load=$(systemctl show "$unit" --property=LoadState --value)
if [[ "$load" != not-found ]]; then
    description=$(systemctl show "$unit" --property=Description --value)
    [[ "$description" == "$marker" ]] || { echo 'unit name is owned by another service' >&2; exit 4; }
fi

if [[ "$action" == reset ]]; then
    if [[ "$load" != not-found ]]; then
        systemctl stop "$unit"
        state=$(systemctl is-active "$unit" 2>/dev/null || true)
        [[ "$state" == inactive || "$state" == failed || "$state" == unknown ]] || exit 5
    fi
    echo 'cpu: reset'
    exit 0
fi
[[ -x /usr/bin/stress-ng ]] || { echo 'stress-ng missing' >&2; exit 3; }
[[ "$(nproc)" == 1 ]] || { echo 'R002 instrumentation requires one available CPU' >&2; exit 3; }
[[ "$load" == not-found ]] || { echo 'previous experiment unit still exists; review/reset it first' >&2; exit 4; }
# The remediation allowlist can target these names; other workloads make this experiment unsafe.
if pgrep -x 'stress-ng|stress|stress-ng-cpu' >/dev/null; then
    echo 'existing stress process; restore and review first' >&2; exit 4
else
    code=$?
    [[ "$code" == 1 ]] || { echo 'cannot inspect processes' >&2; exit 4; }
fi
if [[ "$action" == check ]]; then
    echo 'cpu: ready'
    exit 0
fi
systemd-run --quiet --collect --unit="$unit" --description="$marker" \
    --property=Type=exec --property=Restart=no --property=KillMode=control-group --property=RuntimeMaxSec=3600 \
    /usr/bin/stress-ng --cpu 1 --cpu-load 100 --timeout 3600s >/dev/null
[[ "$(systemctl is-active "$unit" 2>/dev/null || true)" == active ]] || exit 5
echo 'cpu: injected'
