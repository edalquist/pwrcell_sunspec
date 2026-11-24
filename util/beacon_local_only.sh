#!/bin/sh
#
# Configure a Generac PWRcell REbus Beacon for safe local-only (internet-blocked)
# operation. Disables cloud-connectivity watchdogs that cause daily ~25h
# reboots and ~10m eth0 resets, disables Mosquitto AWS IoT bridges that bloat
# mosquitto.db, rotates/truncates runaway lcm_core binary_log, and configures
# local LAN NTP (or disables ntpdate checks) while preserving local Modbus TCP,
# local Mosquitto (port 1883), S58statuspusher, lcm_core, and SSH access.
#
# Compatible with BusyBox ash, dash, and POSIX /bin/sh. Can be copied onto the
# Beacon or streamed over SSH stdin:
#   ssh root@192.168.0.73 'sh -s -- --apply --ntp-server 192.168.0.2' < util/beacon_local_only.sh

set -eu

MODE=""
NTP_SERVER=""
DISABLE_NTP=0
KEEP_CLOUD_BRIDGES=0
KEEP_CLOUD_SERVICES=0
KEEP_BINARY_LOG=0
ROOT=""
DRY_RUN=0

WORK_DIR=""
STAGED_FILES=""

ANY_MONIT_CHANGED=0
MOSQUITTO_CONF_CHANGED=0
UPDATE_MGR_CHANGED=0
NTPDATE_CHANGED=0
LOGROTATE_CHANGED=0

MONIT_BACKUP_LIST=""
MOSQUITTO_PRE_SNAPSHOT=""

log() {
    printf '[beacon-local] %s\n' "$*"
}

warn() {
    printf '[beacon-local] WARNING: %s\n' "$*" >&2
}

err() {
    printf '[beacon-local] ERROR: %s\n' "$*" >&2
}

die() {
    err "$*"
    exit 1
}

cleanup() {
    if [ -n "$STAGED_FILES" ]; then
        OLD_IFS="$IFS"
        IFS='
'
        for f in $STAGED_FILES; do
            [ -n "$f" ] && rm -f "$f" 2>/dev/null || true
        done
        IFS="$OLD_IFS"
    fi
    if [ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ]; then
        rm -rf "$WORK_DIR" 2>/dev/null || true
    fi
}

trap cleanup EXIT INT TERM

usage() {
    cat <<'EOF'
Usage: beacon_local_only.sh <MODE> [OPTIONS]

Hardens a Generac PWRcell REbus Beacon for offline/local-only LAN operation.

Modes (choose exactly one):
  --status              Read-only audit of monit rules, mosquitto, and NTP
  --dry-run             Show planned changes and diffs without modifying files
  --apply               Idempotently apply local-only hardening changes
  --revert              Restore original factory/pre-script files from backup
  -h, --help            Show this help text and exit

Options:
  --ntp-server <host>   Configure local LAN NTP server(s) in /etc/default/ntpdate
                        (fixes any NPSERVERS typo, clears HTPSERVERS, re-enables
                        ntpdate in monit.cfg if previously disabled)
  --disable-ntp         Comment out check program ntpdate in /opt/pika/etc/monit.cfg
                        (mutually exclusive with --ntp-server)
  --keep-cloud-bridges  Leave Mosquitto AWS bridges and mosquitto.db untouched
  --keep-cloud-services Leave autossh and update_manager monit rules untouched
  --keep-binary-log     Leave lcm_core binary_log and logrotate untouched
  --root <dir>          Operate against an alternate root directory (for testing)

Environment overrides (primarily for testing):
  MONIT_BIN                 Monit binary name/path (default: monit)
  MOSQUITTO_INIT            Mosquitto init script (default: <root>/etc/init.d/mosquitto)
  NTPDATE_SYNC_BIN          ntpdate-sync path (default: <root>/usr/bin/ntpdate-sync)
  UPDATE_MGR_INIT           update_manager init (default: <root>/opt/pika/etc/init.d/S90update_manager)
  BINARY_LOG_TRUNCATE_BYTES Truncate binary_log threshold in bytes (default: 104857600)

Examples:
  sh util/beacon_local_only.sh --status
  sh util/beacon_local_only.sh --dry-run --ntp-server 192.168.0.2
  sh util/beacon_local_only.sh --apply --ntp-server 192.168.0.2
  ssh root@192.168.0.73 'sh -s -- --apply --ntp-server 192.168.0.2' < util/beacon_local_only.sh
  ssh root@192.168.0.73 'sh -s -- --revert' < util/beacon_local_only.sh
EOF
}

set_mode() {
    new_mode="$1"
    if [ -n "$MODE" ]; then
        die "Specify only one mode (--status, --dry-run, --apply, or --revert)"
    fi
    MODE="$new_mode"
}

validate_ntp_hosts() {
    val="$1"
    trimmed="$(printf '%s' "$val" | awk 'BEGIN { ORS="" } { gsub(/^[ \t]+|[ \t]+$/, ""); print (NR > 1 ? "\n" : "") $0 }')"
    if [ -z "$trimmed" ]; then
        die "--ntp-server value cannot be empty"
    fi
    if ! printf '%s\n' "$trimmed" | awk '
        NR > 1 { bad = 1 }
        $0 !~ /^[A-Za-z0-9._: -]+$/ { bad = 1 }
        $0 ~ /(^| )-/ { bad = 1 }
        END { exit(bad ? 1 : 0) }
    '; then
        die "Invalid characters in --ntp-server: '$val'"
    fi
    NTP_SERVER="$trimmed"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --status)
            set_mode "status"
            shift
            ;;
        --dry-run)
            set_mode "dry-run"
            DRY_RUN=1
            shift
            ;;
        --apply)
            set_mode "apply"
            shift
            ;;
        --revert)
            set_mode "revert"
            shift
            ;;
        --ntp-server)
            [ $# -ge 2 ] || die "--ntp-server requires an argument"
            validate_ntp_hosts "$2"
            shift 2
            ;;
        --ntp-server=*)
            validate_ntp_hosts "${1#--ntp-server=}"
            shift
            ;;
        --disable-ntp)
            DISABLE_NTP=1
            shift
            ;;
        --keep-cloud-bridges)
            KEEP_CLOUD_BRIDGES=1
            shift
            ;;
        --keep-cloud-services)
            KEEP_CLOUD_SERVICES=1
            shift
            ;;
        --keep-binary-log)
            KEEP_BINARY_LOG=1
            shift
            ;;
        --root)
            [ $# -ge 2 ] || die "--root requires a directory argument"
            ROOT="$2"
            shift 2
            ;;
        --root=*)
            ROOT="${1#--root=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown argument: $1 (use --help for usage)"
            ;;
    esac
done

[ -n "$MODE" ] || die "Missing mode flag (--status, --dry-run, --apply, or --revert). Use --help for usage."

if [ -n "$NTP_SERVER" ] && [ "$DISABLE_NTP" -eq 1 ]; then
    die "--ntp-server and --disable-ntp are mutually exclusive"
fi

while [ -n "$ROOT" ] && [ "${ROOT%/}" != "$ROOT" ]; do
    ROOT="${ROOT%/}"
done

MONIT_CFG="${ROOT}/opt/pika/etc/monit.cfg"
MONIT_D="${ROOT}/opt/pika/etc/monit.d"
MQTT_CLIENT_CFG="${MONIT_D}/mqtt_client.cfg"
CHECK_INTERNET_CFG="${MONIT_D}/check_internet.cfg"
LCM_CORE_CFG="${MONIT_D}/lcm-core.cfg"
AUTOSSH_CFG="${MONIT_D}/autossh.cfg"
UPDATE_MGR_CFG="${MONIT_D}/update_manager.cfg"
MOSQUITTO_CFG_REF="${MONIT_D}/mosquitto.cfg"

MOSQUITTO_CONF="${ROOT}/etc/mosquitto/mosquitto.conf"
MOSQUITTO_DB="${ROOT}/opt/pika/var/lib/mosquitto/mosquitto.db"
MOSQUITTO_DB_NEW="${MOSQUITTO_DB}.new"
NTPDATE_CONF="${ROOT}/etc/default/ntpdate"
NTPDATE_STAMP="${ROOT}/tmp/ntpdate-timestamp"
LOGROTATE_DIR="${ROOT}/etc/logrotate.d"
BINARY_LOG_LOGROTATE="${LOGROTATE_DIR}/lcm_binary_log"
BINARY_LOG="${ROOT}/var/log/lcm_core/binary_log"
BINARY_LOG_TRUNCATE_BYTES="${BINARY_LOG_TRUNCATE_BYTES:-104857600}"
UPDATE_MGR_PID="${ROOT}/var/run/update_manager.pid"

BACKUP_DIR="${ROOT}/opt/pika/var/lib/beacon_local_only_backups"

MONIT_BIN="${MONIT_BIN:-monit}"
MOSQUITTO_INIT="${MOSQUITTO_INIT:-${ROOT}/etc/init.d/mosquitto}"
NTPDATE_SYNC_BIN="${NTPDATE_SYNC_BIN:-${ROOT}/usr/bin/ntpdate-sync}"
UPDATE_MGR_INIT="${UPDATE_MGR_INIT:-${ROOT}/opt/pika/etc/init.d/S90update_manager}"

MANAGED_RELPATHS="opt/pika/etc/monit.d/mqtt_client.cfg
opt/pika/etc/monit.d/check_internet.cfg
opt/pika/etc/monit.d/lcm-core.cfg
opt/pika/etc/monit.d/autossh.cfg
opt/pika/etc/monit.d/update_manager.cfg
opt/pika/etc/monit.cfg
etc/mosquitto/mosquitto.conf
etc/default/ntpdate
etc/logrotate.d/lcm_binary_log"

init_workdir() {
    if [ -z "$WORK_DIR" ]; then
        if command -v mktemp >/dev/null 2>&1; then
            WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/beacon_local_only.XXXXXX")"
        else
            WORK_DIR="${TMPDIR:-/tmp}/beacon_local_only.$$"
            mkdir -p "$WORK_DIR"
        fi
        chmod 700 "$WORK_DIR" 2>/dev/null || true
    fi
}

check_guardrails() {
    if [ ! -d "$MONIT_D" ] || [ ! -f "$MONIT_CFG" ]; then
        die "Target '${ROOT:-/}' does not look like a Generac REbus Beacon (missing $MONIT_D or $MONIT_CFG)"
    fi
    if [ -z "$ROOT" ] && { [ "$MODE" = "apply" ] || [ "$MODE" = "revert" ]; }; then
        if [ "$(id -u)" -ne 0 ]; then
            die "--${MODE} on live system requires root privileges"
        fi
    fi
}

file_size_bytes() {
    if stat -c '%s' "$1" 2>/dev/null; then
        return 0
    fi
    if stat -f '%z' "$1" 2>/dev/null; then
        return 0
    fi
    ls -ln "$1" | awk '{ print $5 }'
}

has_active_monit_rule() {
    file="$1"
    rule_pat="$2"
    [ -f "$file" ] || return 1
    awk -v pat="$rule_pat" '
        $0 ~ pat { found = 1; exit }
        END { exit(found ? 0 : 1) }
    ' "$file"
}

has_disabled_marker_rule() {
    file="$1"
    rule_name="$2"
    [ -f "$file" ] || return 1
    awk -v name="$rule_name" '
        index($0, "# [beacon_local_only] ") == 1 {
            rest = substr($0, 23)
            if (rest ~ ("^check[ \t]+(program|process)[ \t]+" name "([ \t]|$)")) {
                found = 1
                exit
            }
        }
        END { exit(found ? 0 : 1) }
    ' "$file"
}

report_rule_status() {
    label="$1"
    file="$2"
    rule_name="$3"
    if [ ! -f "$file" ]; then
        printf '  %-24s %s\n' "$label:" "file missing ($file)"
        return
    fi
    if has_active_monit_rule "$file" "^check[ \t]+(program|process)[ \t]+${rule_name}([ \t]|$)"; then
        printf '  %-24s %s\n' "$label:" "ACTIVE"
    elif has_disabled_marker_rule "$file" "$rule_name"; then
        printf '  %-24s %s\n' "$label:" "disabled (by beacon_local_only)"
    else
        printf '  %-24s %s\n' "$label:" "inactive/commented"
    fi
}

run_status() {
    log "Audit target: ${ROOT:-/}"
    if [ -z "$ROOT" ]; then
        printf '  %-24s %s\n' "Hostname:" "$(hostname 2>/dev/null || echo unknown)"
        printf '  %-24s %s\n' "Uptime:" "$(uptime 2>/dev/null || echo unknown)"
    fi

    printf '\nCloud-only Monit rules (disabled by local-only hardening):\n'
    report_rule_status "mqtt_reboot" "$MQTT_CLIENT_CFG" "mqtt_reboot"
    report_rule_status "mqtt_active" "$MQTT_CLIENT_CFG" "mqtt_active"
    report_rule_status "ipv6_monitor" "$MQTT_CLIENT_CFG" "ipv6_monitor"
    report_rule_status "internet" "$CHECK_INTERNET_CFG" "internet"
    report_rule_status "inet_good" "$LCM_CORE_CFG" "inet_good"
    report_rule_status "autossh_triggers" "$AUTOSSH_CFG" "autossh_triggers"
    report_rule_status "sshidle_monitor" "$AUTOSSH_CFG" "sshidle_monitor"
    report_rule_status "update_manager" "$UPDATE_MGR_CFG" "update_manager"
    report_rule_status "ntpdate" "$MONIT_CFG" "ntpdate"

    printf '\nEssential local Monit services (must stay ACTIVE):\n'
    report_rule_status "mqtt_client" "$MQTT_CLIENT_CFG" "mqtt_client"
    report_rule_status "lcm_core" "$LCM_CORE_CFG" "lcm_core"
    report_rule_status "mosquitto" "$MOSQUITTO_CFG_REF" "mosquitto"

    printf '\nMosquitto broker:\n'
    if [ -f "$MOSQUITTO_CONF" ]; then
        if awk '/^[ \t]*include_dir[ \t]+\/tmp\/mosquitto([ \t]|$)/ { f=1; exit } END { exit(f?0:1) }' "$MOSQUITTO_CONF"; then
            printf '  %-24s %s\n' "AWS bridges include:" "ACTIVE (include_dir /tmp/mosquitto)"
        else
            printf '  %-24s %s\n' "AWS bridges include:" "disabled"
        fi
        if awk '/^[ \t]*persistence[ \t]+true([ \t]|$)/ { f=1; exit } END { exit(f?0:1) }' "$MOSQUITTO_CONF"; then
            printf '  %-24s %s\n' "persistence:" "true"
        elif awk '/^[ \t]*persistence[ \t]+false([ \t]|$)/ { f=1; exit } END { exit(f?0:1) }' "$MOSQUITTO_CONF"; then
            printf '  %-24s %s\n' "persistence:" "false"
        else
            printf '  %-24s %s\n' "persistence:" "unset"
        fi
    else
        printf '  %-24s %s\n' "mosquitto.conf:" "missing ($MOSQUITTO_CONF)"
    fi

    if [ -e "$MOSQUITTO_DB" ]; then
        db_bytes="$(file_size_bytes "$MOSQUITTO_DB")"
        db_kb=$((db_bytes / 1024))
        if [ "$db_kb" -gt 200 ]; then
            printf '  %-24s %s\n' "mosquitto.db:" "${db_kb} kB (WARNING: exceeds 200 kB threshold)"
        else
            printf '  %-24s %s\n' "mosquitto.db:" "${db_kb} kB"
        fi
    else
        printf '  %-24s %s\n' "mosquitto.db:" "not present"
    fi

    printf '\nNTP configuration:\n'
    if [ -f "$NTPDATE_CONF" ]; then
        ntp_servers="$(awk -F= '/^[ \t]*NTPSERVERS=/{ v=$2; gsub(/["'\'' \t]/, "", v); val=v } END{ print val }' "$NTPDATE_CONF")"
        np_typo="$(awk '/^[ \t]*NPSERVERS=/{ f=1; exit } END{ print (f ? 1 : 0) }' "$NTPDATE_CONF")"
        htp_servers="$(awk -F= '/^[ \t]*HTPSERVERS=/{ v=$2; gsub(/["'\'' \t]/, "", v); val=v } END{ print val }' "$NTPDATE_CONF")"
        if [ "$np_typo" -eq 1 ]; then
            printf '  %-24s %s\n' "NPSERVERS typo:" "DETECTED in $NTPDATE_CONF (ntpdate-sync expects NTPSERVERS=)"
        fi
        printf '  %-24s %s\n' "NTPSERVERS:" "${ntp_servers:-<unset/empty>}"
        printf '  %-24s %s\n' "HTPSERVERS:" "${htp_servers:-<unset/empty>}"
    else
        printf '  %-24s %s\n' "ntpdate config:" "missing ($NTPDATE_CONF)"
    fi
    if [ -f "$NTPDATE_STAMP" ]; then
        printf '  %-24s %s\n' "ntpdate timestamp:" "present ($NTPDATE_STAMP)"
    else
        printf '  %-24s %s\n' "ntpdate timestamp:" "missing ($NTPDATE_STAMP)"
    fi

    printf '\nDisk & backups:\n'
    if [ -f "$BINARY_LOG_LOGROTATE" ]; then
        if grep -q '^# Managed by beacon_local_only\.sh' "$BINARY_LOG_LOGROTATE"; then
            printf '  %-24s %s\n' "binary_log logrotate:" "managed ($BINARY_LOG_LOGROTATE)"
        else
            printf '  %-24s %s\n' "binary_log logrotate:" "custom ($BINARY_LOG_LOGROTATE)"
        fi
    else
        printf '  %-24s %s\n' "binary_log logrotate:" "not configured (risk of 2 GiB cap when offline)"
    fi
    if [ -e "$BINARY_LOG" ]; then
        bin_bytes="$(file_size_bytes "$BINARY_LOG")"
        bin_mb=$((bin_bytes / 1048576))
        if [ "$bin_bytes" -ge "$BINARY_LOG_TRUNCATE_BYTES" ]; then
            printf '  %-24s %s\n' "binary_log:" "${bin_mb} MiB (WARNING: >= 100 MiB; --apply will truncate in place and add logrotate rule)"
        else
            printf '  %-24s %s\n' "binary_log:" "${bin_mb} MiB"
        fi
    else
        printf '  %-24s %s\n' "binary_log:" "not present"
    fi

    if [ -d "$BACKUP_DIR" ]; then
        printf '  %-24s %s\n' "Backups:" "present in $BACKUP_DIR"
    else
        printf '  %-24s %s\n' "Backups:" "none ($BACKUP_DIR)"
    fi
}

# Comment out matching check (program|process) blocks and their indented continuations.
# Stops on blank/non-indented lines and immediately evaluates them for a new match.
comment_monit_blocks() {
    src="$1"
    out="$2"
    pat="$3"
    awk -v pat="$pat" '
        BEGIN {
            prefix = "# [beacon_local_only] "
            in_block = 0
        }
        {
            if (in_block) {
                if ($0 ~ /^[ \t]+[^ \t]/) {
                    print prefix $0
                    next
                }
                in_block = 0
            }
            if ($0 ~ pat) {
                in_block = 1
                print prefix $0
                next
            }
            print $0
        }
    ' "$src" > "$out"
}

uncomment_monit_blocks() {
    src="$1"
    out="$2"
    pat="$3"
    awk -v pat="$pat" '
        BEGIN {
            prefix = "# [beacon_local_only] "
            plen = length(prefix)
            in_block = 0
        }
        {
            has_prefix = (substr($0, 1, plen) == prefix)
            stripped = has_prefix ? substr($0, plen + 1) : $0
            if (in_block) {
                if (has_prefix && stripped ~ /^[ \t]+[^ \t]/) {
                    print stripped
                    next
                }
                in_block = 0
            }
            if (has_prefix && stripped ~ pat) {
                in_block = 1
                print stripped
                next
            }
            print $0
        }
    ' "$src" > "$out"
}

strip_managed_block_and_comment_keys() {
    src="$1"
    out="$2"
    block_tag="$3"
    key_pat="$4"
    block_file="$5"
    awk -v tag="$block_tag" -v pat="$key_pat" -v bfile="$block_file" '
        BEGIN {
            begin_marker = "# BEGIN beacon_local_only " tag
            end_marker = "# END beacon_local_only " tag
            prefix = "# [beacon_local_only] "
            in_managed = 0
            count = 0
        }
        {
            if ($0 == begin_marker) {
                in_managed = 1
                next
            }
            if (in_managed) {
                if ($0 == end_marker) {
                    in_managed = 0
                }
                next
            }
            if ($0 ~ pat) {
                lines[++count] = prefix $0
            } else {
                lines[++count] = $0
            }
        }
        END {
            while (count > 0 && lines[count] ~ /^[ \t]*$/) {
                count--
            }
            for (i = 1; i <= count; i++) {
                print lines[i]
            }
            if (count > 0) {
                print ""
            }
            while ((getline bline < bfile) > 0) {
                print bline
            }
            close(bfile)
        }
    ' "$src" > "$out"
}

revert_file_by_unmarking() {
    src="$1"
    out="$2"
    awk '
        BEGIN {
            prefix = "# [beacon_local_only] "
            plen = length(prefix)
            in_managed = 0
            count = 0
        }
        {
            if ($0 ~ /^# BEGIN beacon_local_only /) {
                in_managed = 1
                next
            }
            if (in_managed) {
                if ($0 ~ /^# END beacon_local_only /) {
                    in_managed = 0
                }
                next
            }
            if (substr($0, 1, plen) == prefix) {
                lines[++count] = substr($0, plen + 1)
            } else {
                lines[++count] = $0
            }
        }
        END {
            while (count > 0 && lines[count] ~ /^[ \t]*$/) {
                count--
            }
            for (i = 1; i <= count; i++) {
                print lines[i]
            }
        }
    ' "$src" > "$out"
}

file_has_markers() {
    [ -f "$1" ] || return 1
    awk '
        index($0, "# [beacon_local_only] ") == 1 || /^# BEGIN beacon_local_only / { found=1; exit }
        END { exit(found ? 0 : 1) }
    ' "$1"
}

backup_original_if_needed() {
    relpath="$1"
    target="${ROOT}/${relpath}"
    bpath="${BACKUP_DIR}/${relpath}"
    [ -f "$target" ] || return 0
    if [ -f "$bpath" ]; then
        return 0
    fi
    if file_has_markers "$target"; then
        return 0
    fi
    mkdir -p "$(dirname "$bpath")"
    cp -p "$target" "$bpath"
}

snapshot_for_rollback() {
    relpath="$1"
    target="${ROOT}/${relpath}"
    snap_dir="${WORK_DIR}/rollback"
    snap_path="${snap_dir}/${relpath}"
    mkdir -p "$(dirname "$snap_path")"
    if [ -f "$target" ]; then
        cp -p "$target" "$snap_path"
    fi
}

track_monit_change() {
    relpath="$1"
    case "
$MONIT_BACKUP_LIST
" in
        *"
$relpath
"*) ;;
        *)
            if [ -z "$MONIT_BACKUP_LIST" ]; then
                MONIT_BACKUP_LIST="$relpath"
            else
                MONIT_BACKUP_LIST="${MONIT_BACKUP_LIST}
${relpath}"
            fi
            ;;
    esac
    ANY_MONIT_CHANGED=1
}

rollback_monit_changes() {
    [ -n "$MONIT_BACKUP_LIST" ] || return 0
    err "Rolling back modified monit configuration files..."
    OLD_IFS="$IFS"
    IFS='
'
    for relpath in $MONIT_BACKUP_LIST; do
        [ -n "$relpath" ] || continue
        snap_path="${WORK_DIR}/rollback/${relpath}"
        target="${ROOT}/${relpath}"
        if [ -f "$snap_path" ]; then
            staged="${target}.beacon_tmp.$$"
            STAGED_FILES="${STAGED_FILES}
${staged}"
            cp -p "$snap_path" "$staged"
            mv "$staged" "$target"
        fi
    done
    IFS="$OLD_IFS"
}

# Apply candidate file atomically while preserving permissions. Sets LAST_CHANGED=0|1.
apply_staged_candidate() {
    relpath="$1"
    cand="$2"
    kind="$3" # monit | mosquitto | ntpdate | other
    target="${ROOT}/${relpath}"

    LAST_CHANGED=0
    if [ -f "$target" ] && cmp -s "$target" "$cand"; then
        return 0
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        if [ -f "$target" ]; then
            log "[dry-run] Would update $target"
            if command -v diff >/dev/null 2>&1; then
                diff -u "$target" "$cand" || true
            fi
        else
            log "[dry-run] Would create $target"
            if command -v diff >/dev/null 2>&1; then
                diff -u /dev/null "$cand" || true
            fi
        fi
        LAST_CHANGED=1
        return 0
    fi

    backup_original_if_needed "$relpath"
    snapshot_for_rollback "$relpath"

    staged="${target}.beacon_tmp.$$"
    STAGED_FILES="${STAGED_FILES}
${staged}"
    if [ -f "$target" ]; then
        cp -p "$target" "$staged"
    else
        mkdir -p "$(dirname "$target")"
        : > "$staged"
        chmod 644 "$staged"
    fi
    cat "$cand" > "$staged"
    mv "$staged" "$target"

    if [ "$kind" = "monit" ]; then
        track_monit_change "$relpath"
    elif [ "$kind" = "mosquitto" ]; then
        MOSQUITTO_CONF_CHANGED=1
    elif [ "$kind" = "ntpdate" ]; then
        NTPDATE_CHANGED=1
    elif [ "$kind" = "logrotate" ]; then
        LOGROTATE_CHANGED=1
    fi

    log "Updated $target"
    LAST_CHANGED=1
}

process_monit_comment_file() {
    relpath="$1"
    pat="$2"
    required="$3"
    target="${ROOT}/${relpath}"
    if [ ! -f "$target" ]; then
        if [ "$required" -eq 1 ]; then
            die "Required monit config missing: $target"
        fi
        return 0
    fi
    cand="${WORK_DIR}/cand_$(printf '%s' "$relpath" | tr '/' '_')"
    comment_monit_blocks "$target" "$cand" "$pat"
    apply_staged_candidate "$relpath" "$cand" "monit"
    if [ "$relpath" = "opt/pika/etc/monit.d/update_manager.cfg" ] && [ "$LAST_CHANGED" -eq 1 ]; then
        UPDATE_MGR_CHANGED=1
    fi
}

process_monit_uncomment_file() {
    relpath="$1"
    pat="$2"
    target="${ROOT}/${relpath}"
    [ -f "$target" ] || return 0
    cand="${WORK_DIR}/cand_$(printf '%s' "$relpath" | tr '/' '_')"
    uncomment_monit_blocks "$target" "$cand" "$pat"
    apply_staged_candidate "$relpath" "$cand" "monit"
}

run_apply_or_dryrun() {
    init_workdir

    # 1. Disable cloud-only checks while keeping mqtt_client and lcm_core intact.
    process_monit_comment_file \
        "opt/pika/etc/monit.d/mqtt_client.cfg" \
        '^check[ \t]+program[ \t]+(mqtt_reboot|mqtt_active|ipv6_monitor)([ \t]|$)' \
        1

    process_monit_comment_file \
        "opt/pika/etc/monit.d/check_internet.cfg" \
        '^check[ \t]+program[ \t]+internet([ \t]|$)' \
        0

    process_monit_comment_file \
        "opt/pika/etc/monit.d/lcm-core.cfg" \
        '^check[ \t]+program[ \t]+inet_good([ \t]|$)' \
        1

    # 2. Optional cloud-only services (autossh, update_manager)
    if [ "$KEEP_CLOUD_SERVICES" -eq 0 ]; then
        process_monit_comment_file \
            "opt/pika/etc/monit.d/autossh.cfg" \
            '^check[ \t]+program[ \t]+(autossh_triggers|sshidle_monitor)([ \t]|$)' \
            0
        process_monit_comment_file \
            "opt/pika/etc/monit.d/update_manager.cfg" \
            '^check[ \t]+process[ \t]+update_manager([ \t]|$)' \
            0
    fi

    # 3. NTP configuration in monit.cfg and /etc/default/ntpdate
    if [ -n "$NTP_SERVER" ]; then
        process_monit_uncomment_file \
            "opt/pika/etc/monit.cfg" \
            '^check[ \t]+program[ \t]+ntpdate([ \t]|$)'

        if [ -f "$NTPDATE_CONF" ]; then
            ntp_block="${WORK_DIR}/ntp_block"
            cat > "$ntp_block" <<EOF
# BEGIN beacon_local_only ntpdate
NTPSERVERS="${NTP_SERVER}"
HTPSERVERS=""
UPDATE_HWCLOCK="yes"
# END beacon_local_only ntpdate
EOF
            cand_ntp="${WORK_DIR}/cand_ntpdate"
            strip_managed_block_and_comment_keys \
                "$NTPDATE_CONF" \
                "$cand_ntp" \
                "ntpdate" \
                '^[ \t]*(NTPSERVERS|NPSERVERS|HTPSERVERS|UPDATE_HWCLOCK)=' \
                "$ntp_block"
            apply_staged_candidate "etc/default/ntpdate" "$cand_ntp" "ntpdate"
        else
            warn "Missing $NTPDATE_CONF; skipping NTPSERVERS update"
        fi
    elif [ "$DISABLE_NTP" -eq 1 ]; then
        process_monit_comment_file \
            "opt/pika/etc/monit.cfg" \
            '^check[ \t]+program[ \t]+ntpdate([ \t]|$)' \
            1
    else
        if [ -f "$NTPDATE_CONF" ]; then
            if awk '/^[ \t]*NPSERVERS=/{ f=1; exit } END{ exit(f?0:1) }' "$NTPDATE_CONF" \
               && ! awk '/^[ \t]*NTPSERVERS=/{ f=1; exit } END{ exit(f?0:1) }' "$NTPDATE_CONF"; then
                warn "$NTPDATE_CONF has 'NPSERVERS=' typo and no 'NTPSERVERS='; re-run with --ntp-server <lan-ip> or --disable-ntp to fix NTP retries"
            fi
        fi
    fi

    # 4. Mosquitto AWS bridges and bloated persistence DB
    mosq_db_exists=0
    if [ -e "$MOSQUITTO_DB" ] || [ -e "$MOSQUITTO_DB_NEW" ]; then
        mosq_db_exists=1
    fi

    if [ "$KEEP_CLOUD_BRIDGES" -eq 0 ]; then
        if [ -f "$MOSQUITTO_CONF" ]; then
            mosq_block="${WORK_DIR}/mosq_block"
            cat > "$mosq_block" <<'EOF'
# BEGIN beacon_local_only mosquitto
persistence false
max_queued_bytes 1048576
max_queued_messages 1000
log_dest file /var/log/mosquitto.log
log_timestamp true
log_timestamp_format %Y-%m-%dT%H:%M:%S
# END beacon_local_only mosquitto
EOF
            if [ -e "$MOSQUITTO_DB" ] || [ -e "$MOSQUITTO_DB_NEW" ]; then
                MOSQUITTO_PRE_SNAPSHOT="${WORK_DIR}/mosquitto_conf_pre"
                cp -p "$MOSQUITTO_CONF" "$MOSQUITTO_PRE_SNAPSHOT"
            fi
            cand_mosq="${WORK_DIR}/cand_mosquitto_conf"
            strip_managed_block_and_comment_keys \
                "$MOSQUITTO_CONF" \
                "$cand_mosq" \
                "mosquitto" \
                '^[ \t]*(include_dir[ \t]+/tmp/mosquitto|persistence|persistence_file|max_queued_bytes|max_queued_messages)([ \t]|$)' \
                "$mosq_block"
            apply_staged_candidate "etc/mosquitto/mosquitto.conf" "$cand_mosq" "mosquitto"
            if [ "$MOSQUITTO_CONF_CHANGED" -eq 1 ]; then
                MOSQUITTO_PRE_SNAPSHOT="${WORK_DIR}/rollback/etc/mosquitto/mosquitto.conf"
            fi
        else
            warn "Missing $MOSQUITTO_CONF; skipping Mosquitto config update"
        fi
    fi

    # 5. Manage /var/log/lcm_core/binary_log logrotate rule & safe O_APPEND truncation
    need_binary_log_truncate=0
    bin_bytes=0
    if [ "$KEEP_BINARY_LOG" -eq 0 ]; then
        if [ -d "$LOGROTATE_DIR" ]; then
            cand_lr="${WORK_DIR}/cand_lcm_binary_log"
            cat > "$cand_lr" <<'EOF'
# Managed by beacon_local_only.sh (local-only mode)
# Rotates lcm_core binary_log (opened O_WRONLY|O_APPEND) when cloud uploads are blocked.
/var/log/lcm_core/binary_log {
    rotate 5
    size 10M
    copytruncate
    missingok
}
EOF
            apply_staged_candidate "etc/logrotate.d/lcm_binary_log" "$cand_lr" "logrotate"
        else
            warn "Missing $LOGROTATE_DIR; skipping binary_log logrotate configuration"
        fi

        if [ -f "$BINARY_LOG" ]; then
            bin_bytes="$(file_size_bytes "$BINARY_LOG")"
            if [ "$bin_bytes" -ge "$BINARY_LOG_TRUNCATE_BYTES" ]; then
                need_binary_log_truncate=1
            fi
        fi
    fi

    # Determine post-config service actions
    need_update_mgr_stop=0
    if [ "$KEEP_CLOUD_SERVICES" -eq 0 ] && [ -x "$UPDATE_MGR_INIT" ]; then
        if [ "$UPDATE_MGR_CHANGED" -eq 1 ] || [ -f "$UPDATE_MGR_PID" ]; then
            need_update_mgr_stop=1
        fi
    fi

    need_mosq_restart=0
    if [ "$KEEP_CLOUD_BRIDGES" -eq 0 ]; then
        if [ "$MOSQUITTO_CONF_CHANGED" -eq 1 ] || [ "$mosq_db_exists" -eq 1 ]; then
            need_mosq_restart=1
        fi
    fi

    need_ntp_sync=0
    if [ -n "$NTP_SERVER" ]; then
        if [ "$NTPDATE_CHANGED" -eq 1 ] || [ ! -f "$NTPDATE_STAMP" ]; then
            need_ntp_sync=1
        fi
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        if [ "$ANY_MONIT_CHANGED" -eq 1 ]; then
            log "[dry-run] Would run: $MONIT_BIN -t && $MONIT_BIN reload"
        fi
        if [ "$need_update_mgr_stop" -eq 1 ]; then
            log "[dry-run] Would run: $UPDATE_MGR_INIT stop"
        fi
        if [ "$need_mosq_restart" -eq 1 ]; then
            log "[dry-run] Would stop mosquitto, remove mosquitto.db*, and start mosquitto"
        fi
        if [ "$need_ntp_sync" -eq 1 ]; then
            log "[dry-run] Would run: $NTPDATE_SYNC_BIN foreground"
        fi
        if [ "$need_binary_log_truncate" -eq 1 ]; then
            log "[dry-run] Would truncate $BINARY_LOG in place ($((bin_bytes / 1048576)) MiB -> 0 MiB)"
        fi
        if [ "$ANY_MONIT_CHANGED" -eq 0 ] && [ "$MOSQUITTO_CONF_CHANGED" -eq 0 ] && [ "$mosq_db_exists" -eq 0 ] && [ "$NTPDATE_CHANGED" -eq 0 ] && [ "$LOGROTATE_CHANGED" -eq 0 ] && [ "$need_update_mgr_stop" -eq 0 ] && [ "$need_ntp_sync" -eq 0 ] && [ "$need_binary_log_truncate" -eq 0 ]; then
            log "[dry-run] Already configured; no changes required."
        fi
        return 0
    fi

    # 5. Validate monit BEFORE reloading; rollback on failure.
    if [ "$ANY_MONIT_CHANGED" -eq 1 ]; then
        log "Validating monit configuration ($MONIT_BIN -t)..."
        if ! "$MONIT_BIN" -t; then
            rollback_monit_changes
            die "$MONIT_BIN -t failed; rolled back monit configuration changes"
        fi
        log "Reloading monit ($MONIT_BIN reload)..."
        "$MONIT_BIN" reload || die "$MONIT_BIN reload failed"
    fi

    # 6. Stop update_manager after monit unmonitors it.
    if [ "$need_update_mgr_stop" -eq 1 ]; then
        log "Stopping update_manager ($UPDATE_MGR_INIT stop)..."
        "$UPDATE_MGR_INIT" stop || warn "$UPDATE_MGR_INIT stop returned non-zero"
    fi

    # 7. Restart Mosquitto cleanly & delete bloated mosquitto.db while stopped.
    if [ "$need_mosq_restart" -eq 1 ]; then
        log "Stopping mosquitto ($MOSQUITTO_INIT stop)..."
        if ! "$MOSQUITTO_INIT" stop; then
            if [ "$MOSQUITTO_CONF_CHANGED" -eq 1 ] && [ -n "$MOSQUITTO_PRE_SNAPSHOT" ] && [ -f "$MOSQUITTO_PRE_SNAPSHOT" ]; then
                staged="${MOSQUITTO_CONF}.beacon_tmp.$$"
                STAGED_FILES="${STAGED_FILES}
${staged}"
                cp -p "$MOSQUITTO_PRE_SNAPSHOT" "$staged"
                mv "$staged" "$MOSQUITTO_CONF"
            fi
            die "$MOSQUITTO_INIT stop failed"
        fi
        rm -f "$MOSQUITTO_DB" "$MOSQUITTO_DB_NEW"
        log "Starting mosquitto ($MOSQUITTO_INIT start)..."
        if ! "$MOSQUITTO_INIT" start; then
            if [ "$MOSQUITTO_CONF_CHANGED" -eq 1 ] && [ -n "$MOSQUITTO_PRE_SNAPSHOT" ] && [ -f "$MOSQUITTO_PRE_SNAPSHOT" ]; then
                err "mosquitto start failed; restoring $MOSQUITTO_CONF..."
                staged="${MOSQUITTO_CONF}.beacon_tmp.$$"
                STAGED_FILES="${STAGED_FILES}
${staged}"
                cp -p "$MOSQUITTO_PRE_SNAPSHOT" "$staged"
                mv "$staged" "$MOSQUITTO_CONF"
                "$MOSQUITTO_INIT" start || true
            fi
            die "$MOSQUITTO_INIT start failed"
        fi
    fi

    # 8. Trigger an immediate NTP sync if ntpdate config changed or timestamp missing.
    if [ "$need_ntp_sync" -eq 1 ]; then
        if [ -x "$NTPDATE_SYNC_BIN" ]; then
            log "Running $NTPDATE_SYNC_BIN foreground..."
            if ! "$NTPDATE_SYNC_BIN" foreground; then
                warn "$NTPDATE_SYNC_BIN foreground failed (check NTP server reachability: $NTP_SERVER)"
            fi
        else
            warn "NTP sync script not executable: $NTPDATE_SYNC_BIN"
        fi
    fi

    # 9. Safely truncate oversized binary_log in place (opened O_APPEND; keeps lcm_core running)
    if [ "$need_binary_log_truncate" -eq 1 ]; then
        bin_mb=$((bin_bytes / 1048576))
        log "Truncating $BINARY_LOG in place (${bin_mb} MiB -> 0 MiB)..."
        : > "$BINARY_LOG"
    fi

    if [ "$ANY_MONIT_CHANGED" -eq 0 ] && [ "$MOSQUITTO_CONF_CHANGED" -eq 0 ] && [ "$mosq_db_exists" -eq 0 ] && [ "$NTPDATE_CHANGED" -eq 0 ] && [ "$LOGROTATE_CHANGED" -eq 0 ] && [ "$need_update_mgr_stop" -eq 0 ] && [ "$need_ntp_sync" -eq 0 ] && [ "$need_binary_log_truncate" -eq 0 ]; then
        log "Already in desired local-only state; no changes needed."
    else
        log "Local-only configuration applied successfully."
    fi
}

run_revert() {
    init_workdir
    reverted_any=0
    RESTORED_BACKUPS=""

    OLD_IFS="$IFS"
    IFS='
'
    for relpath in $MANAGED_RELPATHS; do
        [ -n "$relpath" ] || continue
        target="${ROOT}/${relpath}"
        bpath="${BACKUP_DIR}/${relpath}"
        ropath="${ROOT}/mnt/ro/${relpath}"
        cand="${WORK_DIR}/revert_$(printf '%s' "$relpath" | tr '/' '_')"

        have_candidate=0
        if [ -f "$bpath" ]; then
            cp -p "$bpath" "$cand"
            have_candidate=1
            RESTORED_BACKUPS="${RESTORED_BACKUPS}
${bpath}"
        elif [ "$relpath" = "etc/logrotate.d/lcm_binary_log" ] && [ -f "$target" ] && grep -q '^# Managed by beacon_local_only\.sh' "$target"; then
            rm -f "$target"
            reverted_any=1
            log "Removed $target"
            continue
        elif file_has_markers "$target"; then
            if [ -f "$ropath" ]; then
                cp -p "$ropath" "$cand"
            else
                revert_file_by_unmarking "$target" "$cand"
            fi
            have_candidate=1
        fi

        if [ "$have_candidate" -eq 1 ]; then
            if [ -f "$target" ] && cmp -s "$target" "$cand"; then
                continue
            fi

            snapshot_for_rollback "$relpath"
            staged="${target}.beacon_tmp.$$"
            STAGED_FILES="${STAGED_FILES}
${staged}"
            if [ -f "$bpath" ]; then
                cp -p "$bpath" "$staged"
            elif [ -f "$target" ]; then
                cp -p "$target" "$staged"
                cat "$cand" > "$staged"
            else
                mkdir -p "$(dirname "$target")"
                cp -p "$cand" "$staged"
            fi
            mv "$staged" "$target"
            reverted_any=1
            log "Reverted $target"

            case "$relpath" in
                opt/pika/etc/monit.cfg|opt/pika/etc/monit.d/*)
                    track_monit_change "$relpath"
                    ;;
                etc/mosquitto/mosquitto.conf)
                    MOSQUITTO_CONF_CHANGED=1
                    MOSQUITTO_PRE_SNAPSHOT="${WORK_DIR}/rollback/etc/mosquitto/mosquitto.conf"
                    ;;
            esac
        fi
    done
    IFS="$OLD_IFS"

    if [ "$ANY_MONIT_CHANGED" -eq 1 ]; then
        log "Validating reverted monit configuration ($MONIT_BIN -t)..."
        if ! "$MONIT_BIN" -t; then
            rollback_monit_changes
            die "$MONIT_BIN -t failed during revert; rolled back monit changes"
        fi
        log "Reloading monit ($MONIT_BIN reload)..."
        "$MONIT_BIN" reload || die "$MONIT_BIN reload failed during revert"
    fi

    if [ "$MOSQUITTO_CONF_CHANGED" -eq 1 ]; then
        log "Restarting mosquitto ($MOSQUITTO_INIT restart)..."
        if ! "$MOSQUITTO_INIT" restart; then
            if [ -n "$MOSQUITTO_PRE_SNAPSHOT" ] && [ -f "$MOSQUITTO_PRE_SNAPSHOT" ]; then
                staged="${MOSQUITTO_CONF}.beacon_tmp.$$"
                STAGED_FILES="${STAGED_FILES}
${staged}"
                cp -p "$MOSQUITTO_PRE_SNAPSHOT" "$staged"
                mv "$staged" "$MOSQUITTO_CONF"
                "$MOSQUITTO_INIT" restart || true
            fi
            die "$MOSQUITTO_INIT restart failed during revert"
        fi
    fi

    # Only remove backup files once validation and service reloads succeed.
    if [ -n "$RESTORED_BACKUPS" ]; then
        OLD_IFS="$IFS"
        IFS='
'
        for bpath in $RESTORED_BACKUPS; do
            [ -n "$bpath" ] && [ -f "$bpath" ] && rm -f "$bpath"
        done
        IFS="$OLD_IFS"
        if [ -d "$BACKUP_DIR" ]; then
            find "$BACKUP_DIR" -depth -type d -exec rmdir {} ';' 2>/dev/null || true
        fi
    fi

    if [ "$reverted_any" -eq 0 ] && [ -z "$RESTORED_BACKUPS" ]; then
        log "Nothing to revert; no backups or local-only markers found."
    else
        log "Revert completed successfully."
    fi
}

case "$MODE" in
    status)
        check_guardrails
        run_status
        ;;
    dry-run|apply)
        check_guardrails
        run_apply_or_dryrun
        ;;
    revert)
        check_guardrails
        run_revert
        ;;
    *)
        die "Unsupported mode: $MODE"
        ;;
esac
