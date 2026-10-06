#!/usr/bin/env bash
# Laboratory instrumentation for nginx only; invoked explicitly by the administrator.
set -euo pipefail
[[ $# == 1 ]] || { echo 'expected check, inject or reset' >&2; exit 2; }
action=$1
case "$action" in
    check|inject|reset) ;;
    *) echo 'unsupported scenario action' >&2; exit 2 ;;
esac

service_state() {
    local state
    state=$(systemctl is-active nginx 2>/dev/null || true)
    printf '%s' "$state"
}

if [[ "$action" == check || "$action" == inject ]]; then
    [[ "$(service_state)" == active ]] || { echo 'nginx must be active before injection' >&2; exit 3; }
fi
if [[ "$action" != check ]]; then
    [[ "$(id -u)" == 0 ]] || { echo 'administrative privileges required' >&2; exit 4; }
    if [[ "$action" == inject ]]; then
        systemctl stop nginx
        [[ "$(service_state)" == inactive ]] || { echo 'nginx stop not confirmed' >&2; exit 5; }
        echo 'nginx: inactive'
    else
        systemctl start nginx
        [[ "$(service_state)" == active ]] || { echo 'nginx start not confirmed' >&2; exit 5; }
        echo 'nginx: active'
    fi
else
    echo 'nginx: active'
fi
