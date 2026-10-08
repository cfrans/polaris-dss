#!/usr/bin/env bash
# Disposable R001 data only; never mount, format, or use the root filesystem.
set -euo pipefail
[[ $# == 1 ]] || { echo 'expected prepare, check, check-clean, inject or reset' >&2; exit 2; }
action=$1
case "$action" in prepare|check|check-clean|inject|reset) ;; *) exit 2 ;; esac
[[ "$(id -u)" == 0 ]] || { echo 'administrative privileges required' >&2; exit 3; }
mount=/mnt/polaris_test
archive=$mount/polaris_r001_lab.log.gz
filler=$mount/enchimento.bin
manifest=$mount/.polaris-r001.state
[[ -d "$mount" && ! -L "$mount" && "$(readlink -f "$mount")" == "$mount" ]] || exit 3
mountpoint -q "$mount" || { echo 'test mount is absent' >&2; exit 3; }
device=$(stat -c %d "$mount")
[[ "$device" != "$(stat -c %d /)" ]] || { echo 'test mount shares the root filesystem' >&2; exit 3; }
read -r total used available percentage < <(df -B1 --output=size,used,avail,pcent "$mount" | tail -1)
[[ "$total" =~ ^[0-9]+$ && "$used" =~ ^[0-9]+$ && "$available" =~ ^[0-9]+$ ]] || exit 3
[[ "$total" -ge 1900000000 && "$total" -le 2200000000 ]] || { echo 'expected an isolated 2 GB filesystem' >&2; exit 3; }
shopt -s nullglob dotglob
for entry in "$mount"/*; do
    case "$entry" in
        "$archive"|"$filler"|"$manifest")
            [[ -f "$entry" && ! -L "$entry" && "$(stat -c %h "$entry")" == 1 && "$(stat -c %u "$entry")" == 0 ]] || exit 4 ;;
        "$mount/lost+found")
            [[ -d "$entry" && ! -L "$entry" ]] || exit 4
            contents=("$entry"/*)
            [[ ${#contents[@]} == 0 ]] || { echo 'lost+found contains evidence; refuse cleanup' >&2; exit 4; } ;;
        *) echo 'test filesystem contains unrelated data' >&2; exit 4 ;;
    esac
done
archive_inode=0
filler_inode=0
write_manifest() {
    printf 'polaris-r001-v1 %s %s %s\n' "$device" "$archive_inode" "$filler_inode" > "$manifest"
    chmod 600 "$manifest"
}
if [[ -e "$manifest" ]]; then
    read -r signature saved_device archive_inode filler_inode extra < "$manifest"
    [[ "$signature" == polaris-r001-v1 && "$saved_device" == "$device" && -z "${extra:-}" &&
       "$archive_inode" =~ ^[0-9]+$ && "$filler_inode" =~ ^[0-9]+$ &&
       "$(stat -c %a "$manifest")" == 600 ]] || { echo 'invalid fixture manifest' >&2; exit 4; }
    for file in "$archive" "$filler"; do
        inode=$archive_inode
        [[ "$file" != "$filler" ]] || inode=$filler_inode
        if [[ -e "$file" ]]; then
            [[ "$inode" != 0 && "$(stat -c %i "$file")" == "$inode" ]] || { echo 'fixture was replaced' >&2; exit 4; }
        fi
    done
elif [[ -e "$archive" || -e "$filler" ]]; then
    echo 'untracked fixture files; refuse to overwrite or delete' >&2; exit 4
fi
usage() {
    local value
    value=$(df --output=pcent "$mount" | tail -1 | tr -dc '0-9')
    [[ "$value" =~ ^[0-9]+$ && "$value" -le 100 ]] || return 5
    printf '%s' "$value"
}
if [[ "$action" == check-clean ]]; then
    [[ ! -e "$manifest" && ! -e "$archive" && ! -e "$filler" && "$(usage)" -lt 5 ]] || {
        echo 'test fixture is not empty; review the previous round before reset' >&2; exit 4;
    }
    echo 'disk: clean'
    exit 0
fi
if [[ "$action" == reset ]]; then
    # Only files identified by our manifest can be removed. Other data was rejected above.
    if [[ -e "$manifest" ]]; then
        rm -f -- "$archive" "$filler" "$manifest"
    fi
    [[ "$(usage)" -lt 35 ]] || exit 5
    echo 'disk: reset'
    exit 0
fi
if [[ "$action" == prepare ]]; then
    [[ ! -e "$manifest" && "$(usage)" -lt 5 ]] || { echo 'restore empty fixture before preparing' >&2; exit 4; }
    (set -o noclobber; : > "$manifest")
    write_manifest
    (set -o noclobber; : > "$archive")
    chmod 644 "$archive"
    archive_inode=$(stat -c %i "$archive")
    write_manifest
    dd if=/dev/urandom bs=1M count=400 status=none | gzip -1 > "$archive"
    touch -d '8 days ago' "$archive"
    gzip -t "$archive"
    [[ "$(stat -c %s "$archive")" -ge 400000000 && "$(stat -c %s "$archive")" -le 430000000 ]] || exit 5
    [[ "$(usage)" -lt 35 ]] || exit 5
    echo 'disk: prepared'
    exit 0
fi
[[ -e "$manifest" && -e "$archive" && ! -e "$filler" && "$filler_inode" == 0 && "$(usage)" -lt 35 ]] || {
    echo 'prepare the gzip fixture before starting' >&2; exit 4;
}
[[ "$(stat -c %s "$archive")" -ge 400000000 && "$(stat -c %s "$archive")" -le 430000000 ]] || exit 4
[[ -n "$(find "$archive" -maxdepth 0 -mtime +7 -print)" ]] || exit 4
gzip -t "$archive"
if [[ "$action" == check ]]; then
    echo 'disk: ready'
    exit 0
fi
# GNU df's denominator excludes reserved root blocks. Target 96%, keeping measurable headroom.
fill_bytes=$(( (used + available) * 96 / 100 - used ))
[[ "$fill_bytes" -gt 0 && "$fill_bytes" -lt "$available" ]] || exit 5
(set -o noclobber; : > "$filler")
chmod 600 "$filler"
filler_inode=$(stat -c %i "$filler")
write_manifest
fallocate -l "$fill_bytes" "$filler"
percentage=$(usage)
[[ "$percentage" -ge 96 && "$percentage" -le 98 ]] || { echo 'disk pressure not confirmed' >&2; exit 5; }
echo 'disk: injected'
