#!/bin/sh
#
# Provision an offline Generac PWRcell REbus Beacon SD-card image (or mounted
# overlayfs roots) to add an SSH public key, harden/enable sshd, and ensure
# the iptables/ip6tables firewall accepts SSH on the configured interfaces.
#
# On macOS (or with --docker), this script transparently launches itself inside
# a privileged Alpine Linux container via util/Dockerfile.beacon-provision so the
# Beacon's ext4 rw partition (p7) and SquashFS rootfs (p5/p6) can be inspected
# and modified cleanly.
#
# Compatible with macOS /bin/sh, Alpine BusyBox ash, and Debian dash.
#
# WARNING: UNTESTED against a real Beacon SD-card .img file — covered by unit tests
# against simulated overlay directories only. Always back up your .img and run --dry-run first.

set -eu

MODE=""
IMAGE=""
SSH_KEY=""
INTERFACES="eth0 wlan0"
PORT="22"
NO_IPV6=0
RW_PART=""
RO_PART=""
USE_DOCKER=0
IN_CONTAINER=0

RW_ROOT=""
RO_ROOT=""
FACTORY_ROOT=""

DOCKER_IMAGE="${BEACON_PROVISION_DOCKER_IMAGE:-pwrcell-beacon-provision:local}"
WORK_DIR=""
STAGED_FILES=""
MNT_STACK=""
LOOP_LIST=""

CHANGED_COUNT=0

log() {
    printf '[beacon-provision] %s\n' "$*"
}

warn() {
    printf '[beacon-provision] WARNING: %s\n' "$*" >&2
}

err() {
    printf '[beacon-provision] ERROR: %s\n' "$*" >&2
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

    if [ -n "$MNT_STACK" ]; then
        sync 2>/dev/null || true
        OLD_IFS="$IFS"
        IFS='
'
        for mnt in $MNT_STACK; do
            [ -n "$mnt" ] && umount "$mnt" 2>/dev/null || true
        done
        IFS="$OLD_IFS"
    fi

    if [ -n "$LOOP_LIST" ]; then
        OLD_IFS="$IFS"
        IFS='
'
        for ldev in $LOOP_LIST; do
            [ -n "$ldev" ] && losetup -d "$ldev" 2>/dev/null || true
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
Usage: beacon_provision_image.sh <MODE> (--image <path.img> | --rw-root <dir>) [OPTIONS]

Offline provisioning tool for Generac PWRcell REbus Beacon SD-card images.
Adds an SSH public key to the Beacon's writable ext4 overlay (/rw/user),
configures sshd_config / S50sshd, and ensures iptables opens SSH on LAN/Wi-Fi.

Modes (choose exactly one):
  --status                Read-only audit of SSH key, sshd_config, and firewall
  --dry-run               Preview planned changes and diffs without modifying files
  --apply                 Idempotently provision SSH key, sshd, and firewall
  --revert                Restore original/pre-script files from backup
  -h, --help              Show this help text and exit

Target selection:
  --image <path.img>      Path to a raw Beacon SD-card .img file
  --rw-root <dir>         Path to an already-mounted/extracted rw root (containing user/)
  --ro-root <dir>         Optional lowerdir SquashFS rootfs directory (for --rw-root)
  --factory-root <dir>    Optional factory lowerdir directory (for --rw-root)

Options:
  --ssh-key <path.pub>    OpenSSH public key file (required for --apply and --dry-run)
  --interfaces "<list>"   Space-separated interfaces to open (default: "eth0 wlan0")
  --port <1-65535>        SSH TCP port to enable and open (default: 22)
  --no-ipv6               Do not modify /etc/iptables/rules.v6
  --rw-partition <num>    Override writable ext4 partition number (auto: 7)
  --ro-partition <num>    Override active SquashFS partition (auto: cmdline.txt, 5, 6)
  --docker                Force execution inside Docker container (auto on macOS)
  --in-container          Internal flag used when invoked inside Docker

Examples:
  ./util/beacon_provision_image.sh --status --image ~/beacon-backup.img --ssh-key ~/.ssh/id_ed25519.pub
  ./util/beacon_provision_image.sh --dry-run --image ~/beacon-backup.img --ssh-key ~/.ssh/id_ed25519.pub
  ./util/beacon_provision_image.sh --apply --image ~/beacon-backup.img --ssh-key ~/.ssh/id_ed25519.pub
  ./util/beacon_provision_image.sh --revert --image ~/beacon-backup.img
EOF
}

set_mode() {
    new_mode="$1"
    if [ -n "$MODE" ]; then
        die "Specify only one mode (--status, --dry-run, --apply, or --revert)"
    fi
    MODE="$new_mode"
}

validate_port() {
    case "$1" in
        ''|*[!0-9]*)
            die "Invalid --port '$1': must be an integer 1..65535"
            ;;
    esac
    if [ "$1" -lt 1 ] || [ "$1" -gt 65535 ]; then
        die "Invalid --port '$1': must be between 1 and 65535"
    fi
    PORT="$1"
}

validate_part_num() {
    name="$1"
    val="$2"
    case "$val" in
        ''|*[!0-9]*)
            die "Invalid $name '$val': must be a positive partition number"
            ;;
    esac
    if [ "$val" -lt 1 ]; then
        die "Invalid $name '$val': must be >= 1"
    fi
}

validate_interfaces() {
    raw="$1"
    cleaned="$(printf '%s' "$raw" | awk '
        BEGIN { ORS="" }
        {
            for (i = 1; i <= NF; i++) {
                if (out != "") out = out " "
                out = out $i
            }
        }
        END { print out }
    ')"
    if [ -z "$cleaned" ]; then
        die "--interfaces cannot be empty"
    fi
    if ! printf '%s\n' "$cleaned" | awk '
        {
            for (i = 1; i <= NF; i++) {
                if ($i !~ /^[A-Za-z0-9._+-]+$/) {
                    bad = 1
                }
            }
        }
        END { exit(bad ? 1 : 0) }
    '; then
        die "Invalid interface name in --interfaces: '$raw'"
    fi
    INTERFACES="$cleaned"
}

validate_ssh_key_file() {
    kfile="$1"
    [ -f "$kfile" ] || die "SSH public key file not found: $kfile"
    if grep -q 'PRIVATE KEY' "$kfile"; then
        die "Refusing --ssh-key '$kfile': appears to be a PRIVATE key! Pass a .pub public key."
    fi
    if ! awk '
        /^[ \t]*$/ || /^[ \t]*#/ { next }
        $0 ~ /^(ssh-ed25519|ssh-rsa|ssh-dss|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)[ \t]+[A-Za-z0-9+\/=]+([ \t]+.*)?$/ {
            valid++
            next
        }
        { invalid++ }
        END { exit((valid >= 1 && invalid == 0) ? 0 : 1) }
    ' "$kfile"; then
        die "Invalid or empty OpenSSH public key file: $kfile"
    fi
    if command -v ssh-keygen >/dev/null 2>&1; then
        if ! ssh-keygen -l -f "$kfile" >/dev/null 2>&1; then
            die "ssh-keygen rejected public key file: $kfile"
        fi
    fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --status)
            set_mode "status"
            shift
            ;;
        --dry-run)
            set_mode "dry-run"
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
        --image)
            [ $# -ge 2 ] || die "--image requires a file path"
            IMAGE="$2"
            shift 2
            ;;
        --image=*)
            IMAGE="${1#--image=}"
            shift
            ;;
        --ssh-key)
            [ $# -ge 2 ] || die "--ssh-key requires a file path"
            SSH_KEY="$2"
            shift 2
            ;;
        --ssh-key=*)
            SSH_KEY="${1#--ssh-key=}"
            shift
            ;;
        --interfaces)
            [ $# -ge 2 ] || die "--interfaces requires a value"
            validate_interfaces "$2"
            shift 2
            ;;
        --interfaces=*)
            validate_interfaces "${1#--interfaces=}"
            shift
            ;;
        --port)
            [ $# -ge 2 ] || die "--port requires a port number"
            validate_port "$2"
            shift 2
            ;;
        --port=*)
            validate_port "${1#--port=}"
            shift
            ;;
        --no-ipv6)
            NO_IPV6=1
            shift
            ;;
        --rw-partition)
            [ $# -ge 2 ] || die "--rw-partition requires a partition number"
            validate_part_num "--rw-partition" "$2"
            RW_PART="$2"
            shift 2
            ;;
        --rw-partition=*)
            val="${1#--rw-partition=}"
            validate_part_num "--rw-partition" "$val"
            RW_PART="$val"
            shift
            ;;
        --ro-partition)
            [ $# -ge 2 ] || die "--ro-partition requires a partition number"
            validate_part_num "--ro-partition" "$2"
            RO_PART="$2"
            shift 2
            ;;
        --ro-partition=*)
            val="${1#--ro-partition=}"
            validate_part_num "--ro-partition" "$val"
            RO_PART="$val"
            shift
            ;;
        --rw-root)
            [ $# -ge 2 ] || die "--rw-root requires a directory path"
            RW_ROOT="$2"
            shift 2
            ;;
        --rw-root=*)
            RW_ROOT="${1#--rw-root=}"
            shift
            ;;
        --ro-root)
            [ $# -ge 2 ] || die "--ro-root requires a directory path"
            RO_ROOT="$2"
            shift 2
            ;;
        --ro-root=*)
            RO_ROOT="${1#--ro-root=}"
            shift
            ;;
        --factory-root)
            [ $# -ge 2 ] || die "--factory-root requires a directory path"
            FACTORY_ROOT="$2"
            shift 2
            ;;
        --factory-root=*)
            FACTORY_ROOT="${1#--factory-root=}"
            shift
            ;;
        --docker)
            USE_DOCKER=1
            shift
            ;;
        --in-container)
            IN_CONTAINER=1
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

[ -n "$MODE" ] || die "Missing mode (--status, --dry-run, --apply, or --revert). Use --help for usage."

if [ -n "$IMAGE" ] && [ -n "$RW_ROOT" ]; then
    die "Specify either --image or --rw-root, not both"
fi

if [ -z "$IMAGE" ] && [ -z "$RW_ROOT" ]; then
    die "Specify either --image <path.img> or --rw-root <dir>"
fi

if [ "$MODE" = "apply" ] || [ "$MODE" = "dry-run" ]; then
    [ -n "$SSH_KEY" ] || die "--ssh-key <path.pub> is required for --${MODE}"
fi

if [ -n "$SSH_KEY" ]; then
    validate_ssh_key_file "$SSH_KEY"
fi

if [ -n "$IMAGE" ]; then
    [ -f "$IMAGE" ] || die "Image file not found: $IMAGE"
fi

init_workdir() {
    if [ -z "$WORK_DIR" ]; then
        if command -v mktemp >/dev/null 2>&1; then
            WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/beacon_provision.XXXXXX")"
        else
            WORK_DIR="${TMPDIR:-/tmp}/beacon_provision.$$"
            mkdir -p "$WORK_DIR"
        fi
        chmod 700 "$WORK_DIR" 2>/dev/null || true
    fi
}

strip_trailing_slashes() {
    val="$1"
    while [ -n "$val" ] && [ "${val%/}" != "$val" ]; do
        val="${val%/}"
    done
    printf '%s' "$val"
}

push_mount() {
    if [ -z "$MNT_STACK" ]; then
        MNT_STACK="$1"
    else
        MNT_STACK="${1}
${MNT_STACK}"
    fi
}

push_loop() {
    if [ -z "$LOOP_LIST" ]; then
        LOOP_LIST="$1"
    else
        LOOP_LIST="${1}
${LOOP_LIST}"
    fi
}

launch_docker() {
    command -v docker >/dev/null 2>&1 || die "docker CLI not found (required on macOS to mount ext4 Beacon images)"
    if ! docker info >/dev/null 2>&1; then
        die "Docker daemon is not running (start Docker Desktop, OrbStack, or Colima)"
    fi

    [ -n "$IMAGE" ] || die "--image <path.img> is required when launching Docker"

    script_dir="$(cd "$(dirname "$0")" && pwd)"
    dockerfile_path="${script_dir}/Dockerfile.beacon-provision"
    [ -f "$dockerfile_path" ] || die "Dockerfile not found: $dockerfile_path"

    log "Building Docker provisioning image ($DOCKER_IMAGE)..."
    docker build -q -f "$dockerfile_path" -t "$DOCKER_IMAGE" "$script_dir" >/dev/null

    img_dir="$(cd "$(dirname "$IMAGE")" && pwd)"
    img_base="$(basename "$IMAGE")"
    if [ "$MODE" = "status" ] || [ "$MODE" = "dry-run" ]; then
        img_mode="ro"
    else
        img_mode="rw"
    fi

    set -- docker run --rm --privileged \
        -v "${img_dir}:/work/img:${img_mode}"

    if [ -n "$SSH_KEY" ]; then
        key_dir="$(cd "$(dirname "$SSH_KEY")" && pwd)"
        key_base="$(basename "$SSH_KEY")"
        set -- "$@" -v "${key_dir}/${key_base}:/work/ssh_key.pub:ro"
    fi

    set -- "$@" "$DOCKER_IMAGE" --in-container "--${MODE}" --image "/work/img/${img_base}" \
        --interfaces "$INTERFACES" --port "$PORT"

    if [ -n "$SSH_KEY" ]; then
        set -- "$@" --ssh-key "/work/ssh_key.pub"
    fi
    if [ "$NO_IPV6" -eq 1 ]; then
        set -- "$@" --no-ipv6
    fi
    if [ -n "$RW_PART" ]; then
        set -- "$@" --rw-partition "$RW_PART"
    fi
    if [ -n "$RO_PART" ]; then
        set -- "$@" --ro-partition "$RO_PART"
    fi

    exec "$@"
}

if [ "$IN_CONTAINER" -eq 0 ] && [ -z "$RW_ROOT" ]; then
    if [ "$USE_DOCKER" -eq 1 ] || [ "$(uname -s)" = "Darwin" ]; then
        launch_docker
    fi
fi

get_partition_bounds() {
    sfdisk_file="$1"
    part_num="$2"
    awk -v pnum="$part_num" '
        BEGIN { ssz = 512 }
        /^sector-size:/ { ssz = $2 + 0; next }
        {
            cpos = index($0, " : ")
            if (cpos > 0) {
                head = substr($0, 1, cpos - 1)
                if (match(head, /[0-9]+$/)) {
                    tok = substr(head, RSTART, RLENGTH)
                    if (tok == pnum) {
                        s = 0; sz = 0
                        if (match($0, /start=[ \t]*[0-9]+/)) {
                            tmp = substr($0, RSTART, RLENGTH)
                            sub(/start=[ \t]*/, "", tmp)
                            s = tmp + 0
                        }
                        if (match($0, /size=[ \t]*[0-9]+/)) {
                            tmp = substr($0, RSTART, RLENGTH)
                            sub(/size=[ \t]*/, "", tmp)
                            sz = tmp + 0
                        }
                        if (sz > 0) {
                            printf "%.0f %.0f\n", s * ssz, sz * ssz
                            found = 1
                            exit
                        }
                    }
                }
            }
        }
        END { if (!found) exit 1 }
    ' "$sfdisk_file"
}

mount_image_partitions() {
    [ "$(id -u)" -eq 0 ] || die "--image mode requires root privileges (or use --docker)"
    command -v sfdisk >/dev/null 2>&1 || die "sfdisk is required for --image mode"
    command -v losetup >/dev/null 2>&1 || die "losetup is required for --image mode"

    init_workdir
    sfdisk_out="${WORK_DIR}/sfdisk.txt"
    sfdisk -d "$IMAGE" > "$sfdisk_out" || die "Failed to read partition table from $IMAGE"

    # Resolve RW partition (default p7)
    rw_p="${RW_PART:-7}"
    rw_bounds="$(get_partition_bounds "$sfdisk_out" "$rw_p")" || die "Writable partition p${rw_p} not found in $IMAGE"
    rw_off="${rw_bounds%% *}"
    rw_sz="${rw_bounds#* }"

    # Detect active SquashFS RO partition from boot/cmdline.txt if not overridden
    ro_p="$RO_PART"
    if [ -z "$ro_p" ]; then
        if p1_bounds="$(get_partition_bounds "$sfdisk_out" 1 2>/dev/null)"; then
            p1_off="${p1_bounds%% *}"
            p1_sz="${p1_bounds#* }"
            boot_mnt="${WORK_DIR}/boot"
            mkdir -p "$boot_mnt"
            if mount -o "ro,loop,offset=${p1_off},sizelimit=${p1_sz}" "$IMAGE" "$boot_mnt" 2>/dev/null; then
                if [ -f "${boot_mnt}/cmdline.txt" ]; then
                    detected_p="$(awk '
                        {
                            if (match($0, /root=\/dev\/mmcblk0p[0-9]+/)) {
                                s = substr($0, RSTART, RLENGTH)
                                sub(/root=\/dev\/mmcblk0p/, "", s)
                                print s
                                exit
                            }
                        }
                    ' "${boot_mnt}/cmdline.txt")"
                    if [ -n "$detected_p" ]; then
                        ro_p="$detected_p"
                    fi
                fi
                umount "$boot_mnt" 2>/dev/null || true
            fi
        fi
    fi

    if [ -z "$ro_p" ]; then
        if get_partition_bounds "$sfdisk_out" 5 >/dev/null 2>&1; then
            ro_p="5"
        elif get_partition_bounds "$sfdisk_out" 6 >/dev/null 2>&1; then
            ro_p="6"
        else
            die "Could not find SquashFS rootfs partition (p5/p6) in $IMAGE; specify --ro-partition"
        fi
    fi

    ro_bounds="$(get_partition_bounds "$sfdisk_out" "$ro_p")" || die "SquashFS partition p${ro_p} not found in $IMAGE"
    ro_off="${ro_bounds%% *}"
    ro_sz="${ro_bounds#* }"

    RO_ROOT="${WORK_DIR}/ro"
    mkdir -p "$RO_ROOT"
    if mount -t squashfs -o "ro,loop,offset=${ro_off},sizelimit=${ro_sz}" "$IMAGE" "$RO_ROOT" 2>/dev/null; then
        push_mount "$RO_ROOT"
    else
        command -v unsquashfs >/dev/null 2>&1 || die "Cannot mount SquashFS and unsquashfs is not installed"
        ro_loop="$(losetup -r -f --show -o "$ro_off" --sizelimit "$ro_sz" "$IMAGE")" || die "losetup failed for SquashFS partition p${ro_p}"
        push_loop "$ro_loop"
        if ! unsquashfs -n -q -f -d "$RO_ROOT" "$ro_loop" etc/iptables etc/ssh etc/init.d/S50sshd root/.ssh >/dev/null 2>&1; then
            unsquashfs -n -q -f -d "$RO_ROOT" "$ro_loop" >/dev/null 2>&1 || warn "unsquashfs returned warnings reading p${ro_p}"
        fi
        losetup -d "$ro_loop" 2>/dev/null || true
        LOOP_LIST=""
    fi

    # Optional p3 factory lowerdir
    if p3_bounds="$(get_partition_bounds "$sfdisk_out" 3 2>/dev/null)"; then
        p3_off="${p3_bounds%% *}"
        p3_sz="${p3_bounds#* }"
        fac_mnt="${WORK_DIR}/factory"
        mkdir -p "$fac_mnt"
        if mount -o "ro,loop,offset=${p3_off},sizelimit=${p3_sz}" "$IMAGE" "$fac_mnt" 2>/dev/null; then
            push_mount "$fac_mnt"
            FACTORY_ROOT="$fac_mnt"
        fi
    fi

    # Mount p7 ext4 writable /rw partition via explicit loop device so cleanup always detaches it
    rw_mnt="${WORK_DIR}/rw"
    mkdir -p "$rw_mnt"
    if [ "$MODE" = "status" ] || [ "$MODE" = "dry-run" ]; then
        rw_loop="$(losetup -r -f --show -o "$rw_off" --sizelimit "$rw_sz" "$IMAGE")" || die "losetup failed for RW partition p${rw_p}"
        push_loop "$rw_loop"
        if ! mount -t ext4 -o ro,noload "$rw_loop" "$rw_mnt" 2>/dev/null; then
            mount -o ro "$rw_loop" "$rw_mnt" || die "Failed to mount RW partition p${rw_p} read-only"
        fi
    else
        rw_loop="$(losetup -f --show -o "$rw_off" --sizelimit "$rw_sz" "$IMAGE")" || die "losetup failed for RW partition p${rw_p}"
        push_loop "$rw_loop"
        mount -t ext4 -o rw "$rw_loop" "$rw_mnt" || die "Failed to mount RW partition p${rw_p} read-write"
    fi
    push_mount "$rw_mnt"
    RW_ROOT="$rw_mnt"

    log "Mounted image '$IMAGE' (ro=p${ro_p}, rw=p${rw_p})"
}

if [ -n "$IMAGE" ]; then
    mount_image_partitions
fi

RW_ROOT="$(strip_trailing_slashes "$RW_ROOT")"
RO_ROOT="$(strip_trailing_slashes "$RO_ROOT")"
FACTORY_ROOT="$(strip_trailing_slashes "$FACTORY_ROOT")"

USER_DIR="${RW_ROOT}/user"
[ -d "$USER_DIR" ] || die "Invalid writable root '${RW_ROOT}': expected overlay upperdir '${USER_DIR}'"

BACKUP_DIR="${USER_DIR}/opt/pika/var/lib/beacon_provision_backups"

MANAGED_RELPATHS="root/.ssh/authorized_keys
etc/ssh/sshd_config
etc/init.d/S50sshd
etc/iptables/rules.v4
etc/iptables/rules.v6"

# Resolve effective file path across overlayfs layers (sets RESOLVED_PATH and RESOLVED_LAYER).
resolve_source() {
    _rs_rel="$1"
    RESOLVED_PATH=""
    RESOLVED_LAYER=""

    _rs_upper="${USER_DIR}/${_rs_rel}"
    if [ -c "$_rs_upper" ]; then
        RESOLVED_LAYER="whiteout"
        return 1
    fi
    if [ -f "$_rs_upper" ]; then
        RESOLVED_PATH="$_rs_upper"
        RESOLVED_LAYER="rw/user"
        return 0
    fi

    if [ -n "$FACTORY_ROOT" ]; then
        _rs_fac="${FACTORY_ROOT}/${_rs_rel}"
        if [ -c "$_rs_fac" ]; then
            RESOLVED_LAYER="whiteout"
            return 1
        fi
        if [ -f "$_rs_fac" ]; then
            RESOLVED_PATH="$_rs_fac"
            RESOLVED_LAYER="factory"
            return 0
        fi
    fi

    if [ -n "$RO_ROOT" ]; then
        _rs_ro="${RO_ROOT}/${_rs_rel}"
        if [ -f "$_rs_ro" ]; then
            RESOLVED_PATH="$_rs_ro"
            RESOLVED_LAYER="ro"
            return 0
        fi
    fi

    return 1
}

apply_root_ownership_if_uid0() {
    if [ "$(id -u)" -eq 0 ]; then
        chown 0:0 "$1" 2>/dev/null || true
    fi
}

ensure_overlay_parent_dirs() {
    _eop_rel="$1"
    _eop_cur="$USER_DIR"
    _eop_rest="$(dirname "$_eop_rel")"
    [ "$_eop_rest" != "." ] || return 0

    _eop_old_ifs="$IFS"
    IFS='/'
    set -- $_eop_rest
    IFS="$_eop_old_ifs"

    _eop_acc=""
    for _eop_comp in "$@"; do
        [ -n "$_eop_comp" ] || continue
        if [ -z "$_eop_acc" ]; then
            _eop_acc="$_eop_comp"
        else
            _eop_acc="${_eop_acc}/${_eop_comp}"
        fi
        _eop_cur="${_eop_cur}/${_eop_comp}"
        if [ ! -d "$_eop_cur" ]; then
            mkdir -p "$_eop_cur"
            case "$_eop_acc" in
                root|root/.ssh)
                    chmod 700 "$_eop_cur"
                    ;;
                *)
                    chmod 755 "$_eop_cur"
                    ;;
            esac
            apply_root_ownership_if_uid0 "$_eop_cur"
        fi
    done
    # Ensure root and root/.ssh retain strict permissions required by sshd StrictModes
    if [ -d "${USER_DIR}/root/.ssh" ]; then
        chmod 700 "${USER_DIR}/root/.ssh"
        apply_root_ownership_if_uid0 "${USER_DIR}/root/.ssh"
    fi
    if [ -d "${USER_DIR}/root" ]; then
        _eop_mode_str="$(ls -ld "${USER_DIR}/root" | awk '{ print substr($1, 6, 1) substr($1, 9, 1) }')"
        if [ "$_eop_mode_str" != "--" ]; then
            chmod 755 "${USER_DIR}/root"
        fi
        apply_root_ownership_if_uid0 "${USER_DIR}/root"
    fi
}

file_has_markers() {
    [ -f "$1" ] || return 1
    awk '
        index($0, "# [beacon_provision] ") == 1 || /^# BEGIN beacon_provision / { found=1; exit }
        END { exit(found ? 0 : 1) }
    ' "$1"
}

backup_before_edit() {
    _bbe_rel="$1"
    _bbe_target="${USER_DIR}/${_bbe_rel}"
    _bbe_bpath="${BACKUP_DIR}/${_bbe_rel}"
    _bbe_cpath="${_bbe_bpath}.created"

    if [ -f "$_bbe_bpath" ] || [ -f "$_bbe_cpath" ]; then
        return 0
    fi

    mkdir -p "$(dirname "$_bbe_bpath")"
    if [ -f "$_bbe_target" ]; then
        if ! file_has_markers "$_bbe_target"; then
            cp -p "$_bbe_target" "$_bbe_bpath"
        fi
    else
        : > "$_bbe_cpath"
    fi
}

# Stage and atomically write USER_DIR/<relpath> with desired mode (dry-run aware).
write_overlay_file() {
    _wof_rel="$1"
    _wof_cand="$2"
    _wof_mode="$3"
    _wof_target="${USER_DIR}/${_wof_rel}"

    # Treat non-whiteout resolved source as comparison baseline for dry-run diffs
    _wof_cmp_src=""
    if resolve_source "$_wof_rel"; then
        _wof_cmp_src="$RESOLVED_PATH"
    fi

    if [ -f "$_wof_target" ] && cmp -s "$_wof_target" "$_wof_cand"; then
        _wof_cur_ok=1
        if [ "$_wof_mode" = "755" ] && [ ! -x "$_wof_target" ]; then
            _wof_cur_ok=0
        fi
        if [ "$_wof_cur_ok" -eq 1 ]; then
            return 0
        fi
    elif [ ! -f "$_wof_target" ] && [ ! -c "$_wof_target" ] && [ -n "$_wof_cmp_src" ] && cmp -s "$_wof_cmp_src" "$_wof_cand"; then
        _wof_mode_ok=1
        if [ "$_wof_mode" = "755" ] && [ ! -x "$_wof_cmp_src" ]; then
            _wof_mode_ok=0
        fi
        if [ "$_wof_mode_ok" -eq 1 ]; then
            return 0
        fi
    fi

    if [ "$MODE" = "dry-run" ]; then
        if [ -n "$_wof_cmp_src" ]; then
            if cmp -s "$_wof_cmp_src" "$_wof_cand"; then
                log "[dry-run] Would copy and chmod $_wof_mode $_wof_target"
            else
                log "[dry-run] Would update $_wof_target (from ${RESOLVED_LAYER}, mode $_wof_mode)"
                if command -v diff >/dev/null 2>&1; then
                    diff -u "$_wof_cmp_src" "$_wof_cand" || true
                fi
            fi
        else
            log "[dry-run] Would create $_wof_target (mode $_wof_mode)"
            if command -v diff >/dev/null 2>&1; then
                diff -u /dev/null "$_wof_cand" || true
            fi
        fi
        CHANGED_COUNT=$((CHANGED_COUNT + 1))
        return 0
    fi

    backup_before_edit "$_wof_rel"
    ensure_overlay_parent_dirs "$_wof_rel"

    if [ -c "$_wof_target" ]; then
        rm -f "$_wof_target"
    fi

    _wof_staged="${_wof_target}.provision_tmp.$$"
    STAGED_FILES="${STAGED_FILES}
${_wof_staged}"
    cp "$_wof_cand" "$_wof_staged"
    chmod "$_wof_mode" "$_wof_staged"
    apply_root_ownership_if_uid0 "$_wof_staged"
    mv "$_wof_staged" "$_wof_target"

    CHANGED_COUNT=$((CHANGED_COUNT + 1))
    log "Updated $_wof_target (mode $_wof_mode)"
}

build_authorized_keys_candidate() {
    cand="$1"
    keyfile="$2"
    existing=""
    if resolve_source "root/.ssh/authorized_keys"; then
        existing="$RESOLVED_PATH"
    fi

    if [ -n "$existing" ]; then
        cp "$existing" "$cand"
    else
        : > "$cand"
    fi

    awk -v existing_file="$cand" '
        BEGIN {
            count = 0
            while ((getline line < existing_file) > 0) {
                lines[++count] = line
                if (line !~ /^[ \t]*$/ && line !~ /^[ \t]*#/) {
                    n = split(line, f, /[ \t]+/)
                    if (n >= 2) {
                        seen[f[1] " " f[2]] = 1
                    }
                }
            }
            close(existing_file)
        }
        {
            if ($0 ~ /^[ \t]*$/ || $0 ~ /^[ \t]*#/) {
                next
            }
            sig = $1 " " $2
            if (!(sig in seen)) {
                seen[sig] = 1
                lines[++count] = $0
            }
        }
        END {
            for (i = 1; i <= count; i++) {
                print lines[i]
            }
        }
    ' "$keyfile" > "${cand}.new"
    mv "${cand}.new" "$cand"
}

build_sshd_config_candidate() {
    cand="$1"
    port="$2"
    src=""
    if resolve_source "etc/ssh/sshd_config"; then
        src="$RESOLVED_PATH"
    fi

    block_file="${WORK_DIR}/sshd_block"
    cat > "$block_file" <<EOF
# BEGIN beacon_provision sshd
Port ${port}
PermitRootLogin prohibit-password
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
# END beacon_provision sshd
EOF

    if [ -z "$src" ]; then
        cp "$block_file" "$cand"
        return 0
    fi

    awk -v bfile="$block_file" '
        BEGIN {
            prefix = "# [beacon_provision] "
            in_managed = 0
            in_match = 0
            count = 0
        }
        {
            if ($0 == "# BEGIN beacon_provision sshd") {
                in_managed = 1
                next
            }
            if (in_managed) {
                if ($0 == "# END beacon_provision sshd") {
                    in_managed = 0
                }
                next
            }
            if ($0 ~ /^[ \t]*[Mm][Aa][Tt][Cc][Hh]([ \t]|$)/) {
                in_match = 1
            }
            if (!in_match && $0 ~ /^[ \t]*[A-Za-z]+([ \t]|$)/) {
                kw = tolower($1)
                if (kw == "port" || kw == "permitrootlogin" || kw == "pubkeyauthentication" || kw == "authorizedkeysfile") {
                    lines[++count] = prefix $0
                    next
                }
            }
            lines[++count] = $0
        }
        END {
            start = 1
            while (start <= count && lines[start] ~ /^[ \t]*$/) {
                start++
            }
            while ((getline bline < bfile) > 0) {
                print bline
            }
            close(bfile)
            if (start <= count) {
                print ""
                for (i = start; i <= count; i++) {
                    print lines[i]
                }
            }
        }
    ' "$src" > "$cand"
}

build_iptables_candidate() {
    src="$1"
    cand="$2"
    ifaces="$3"
    port="$4"

    awk -v ifaces="$ifaces" -v port="$port" '
        BEGIN {
            prefix = "# [beacon_provision] "
            n_if = split(ifaces, if_arr, /[ \t]+/)
            for (i = 1; i <= n_if; i++) {
                if (if_arr[i] != "") {
                    target_if[if_arr[i]] = 1
                }
            }
            in_managed = 0
            in_filter = 0
            f_count = 0
        }
        function extract_arg(line, flag,    n, a, k) {
            n = split(line, a, /[ \t]+/)
            for (k = 1; k < n; k++) {
                if (a[k] == flag) {
                    return a[k + 1]
                }
            }
            return ""
        }
        function is_input_rule(line) {
            return (line ~ /^[ \t]*-A[ \t]+INPUT([ \t]|$)/)
        }
        function is_tcp_or_all(line,    p) {
            p = extract_arg(line, "-p")
            return (p == "" || p == "tcp" || p == "all")
        }
        function flush_filter(    i, iface, line, ln_iface, ln_target, ln_dport, ln_p, anchor, emitted, j, need_cnt, need_list) {
            delete accepted
            delete blocked
            anchor = 0

            # Pass 1: comment conflicting explicit port drops and track acceptance before blockers
            for (i = 1; i <= f_count; i++) {
                line = flines[i]
                if (!is_input_rule(line)) {
                    continue
                }
                if (anchor == 0) {
                    anchor = i
                }
                if (line ~ /RELATED,ESTABLISHED/ && line ~ /-j[ \t]+ACCEPT([ \t]|$)/) {
                    anchor = i + 1
                }

                ln_iface = extract_arg(line, "-i")
                ln_target = extract_arg(line, "-j")
                ln_dport = extract_arg(line, "--dport")
                ln_p = extract_arg(line, "-p")

                if (ln_iface in target_if) {
                    if (ln_p == "tcp" && ln_dport == port && (ln_target == "DROP" || ln_target == "REJECT")) {
                        flines[i] = prefix line
                        continue
                    }
                    if (!(ln_iface in blocked)) {
                        if (ln_target == "ACCEPT" && is_tcp_or_all(line) && (ln_dport == port || ln_dport == "")) {
                            accepted[ln_iface] = 1
                        } else if ((ln_target == "DROP" || ln_target == "REJECT") && is_tcp_or_all(line) && (ln_dport == "" || ln_dport == port)) {
                            blocked[ln_iface] = 1
                        }
                    }
                }
            }

            need_cnt = 0
            for (i = 1; i <= n_if; i++) {
                iface = if_arr[i]
                if (iface != "" && !(iface in accepted)) {
                    need_list[++need_cnt] = iface
                }
            }

            if (need_cnt > 0 && anchor == 0) {
                anchor = f_count + 1
            }

            emitted = 0
            for (i = 1; i <= f_count; i++) {
                if (need_cnt > 0 && !emitted && i == anchor) {
                    print "# BEGIN beacon_provision ssh"
                    for (j = 1; j <= need_cnt; j++) {
                        print "-A INPUT -i " need_list[j] " -p tcp --dport " port " -j ACCEPT"
                    }
                    print "# END beacon_provision ssh"
                    emitted = 1
                }
                print flines[i]
            }
            if (need_cnt > 0 && !emitted) {
                print "# BEGIN beacon_provision ssh"
                for (j = 1; j <= need_cnt; j++) {
                    print "-A INPUT -i " need_list[j] " -p tcp --dport " port " -j ACCEPT"
                }
                print "# END beacon_provision ssh"
            }
            delete flines
            f_count = 0
        }
        {
            if ($0 == "# BEGIN beacon_provision ssh") {
                in_managed = 1
                next
            }
            if (in_managed) {
                if ($0 == "# END beacon_provision ssh") {
                    in_managed = 0
                }
                next
            }

            if ($0 ~ /^[ \t]*\*filter([ \t]*$)/) {
                in_filter = 1
                f_count = 0
                print $0
                next
            }

            if (in_filter) {
                if ($0 ~ /^[ \t]*COMMIT([ \t]*$)/) {
                    flush_filter()
                    in_filter = 0
                    print $0
                    next
                }
                flines[++f_count] = $0
                next
            }

            print $0
        }
        END {
            if (in_filter && f_count > 0) {
                flush_filter()
            }
        }
    ' "$src" > "$cand"
}

check_iptables_status() {
    src="$1"
    ifaces="$2"
    port="$3"
    awk -v ifaces="$ifaces" -v port="$port" '
        BEGIN {
            n_if = split(ifaces, if_arr, /[ \t]+/)
            for (i = 1; i <= n_if; i++) {
                if (if_arr[i] != "") target_if[if_arr[i]] = 1
            }
            in_filter = 0
        }
        function extract_arg(line, flag,    n, a, k) {
            n = split(line, a, /[ \t]+/)
            for (k = 1; k < n; k++) {
                if (a[k] == flag) return a[k + 1]
            }
            return ""
        }
        /^[ \t]*\*filter([ \t]*$)/ { in_filter = 1; next }
        in_filter && /^[ \t]*COMMIT([ \t]*$)/ { in_filter = 0; next }
        in_filter && /^[ \t]*-A[ \t]+INPUT([ \t]|$)/ {
            ln_iface = extract_arg($0, "-i")
            ln_target = extract_arg($0, "-j")
            ln_dport = extract_arg($0, "--dport")
            ln_p = extract_arg($0, "-p")
            if (ln_iface in target_if) {
                if (!(ln_iface in blocked) && !(ln_iface in accepted)) {
                    if (ln_target == "ACCEPT" && (ln_p == "" || ln_p == "tcp" || ln_p == "all") && (ln_dport == port || ln_dport == "")) {
                        accepted[ln_iface] = 1
                    } else if ((ln_target == "DROP" || ln_target == "REJECT") && (ln_p == "" || ln_p == "tcp" || ln_p == "all") && (ln_dport == "" || ln_dport == port)) {
                        blocked[ln_iface] = 1
                    }
                }
            }
        }
        END {
            for (i = 1; i <= n_if; i++) {
                iface = if_arr[i]
                if (iface != "") {
                    if (iface in accepted) {
                        printf "%s=OPEN\n", iface
                    } else {
                        printf "%s=BLOCKED\n", iface
                    }
                }
            }
        }
    ' "$src"
}

run_status() {
    log "Audit writable root: $RW_ROOT"
    [ -n "$RO_ROOT" ] && printf '  %-24s %s\n' "Lowerdir (ro):" "$RO_ROOT"
    [ -n "$FACTORY_ROOT" ] && printf '  %-24s %s\n' "Lowerdir (factory):" "$FACTORY_ROOT"
    printf '  %-24s %s\n' "Target port:" "$PORT"
    printf '  %-24s %s\n' "Target interfaces:" "$INTERFACES"

    printf '\nSSH service & daemon config:\n'
    if resolve_source "etc/init.d/S50sshd"; then
        if [ -x "$RESOLVED_PATH" ]; then
            printf '  %-24s %s\n' "S50sshd:" "executable (${RESOLVED_LAYER})"
        else
            printf '  %-24s %s\n' "S50sshd:" "NOT executable (${RESOLVED_LAYER})"
        fi
    else
        printf '  %-24s %s\n' "S50sshd:" "${RESOLVED_LAYER:-missing}"
    fi

    if resolve_source "etc/ssh/sshd_config"; then
        printf '  %-24s %s\n' "sshd_config source:" "$RESOLVED_LAYER"
        awk '
            /^[ \t]*[Mm][Aa][Tt][Cc][Hh]([ \t]|$)/ { in_match = 1 }
            !in_match && /^[ \t]*[A-Za-z]+([ \t]|$)/ {
                kw = tolower($1)
                if (kw == "port" && !(kw in seen)) seen[kw] = $2
                if (kw == "permitrootlogin" && !(kw in seen)) seen[kw] = $2
                if (kw == "pubkeyauthentication" && !(kw in seen)) seen[kw] = $2
                if (kw == "authorizedkeysfile" && !(kw in seen)) seen[kw] = $2
            }
            END {
                printf "  %-24s %s\n", "Port:", ("port" in seen ? seen["port"] : "default (22)")
                printf "  %-24s %s\n", "PermitRootLogin:", ("permitrootlogin" in seen ? seen["permitrootlogin"] : "default (prohibit-password)")
                printf "  %-24s %s\n", "PubkeyAuthentication:", ("pubkeyauthentication" in seen ? seen["pubkeyauthentication"] : "default (yes)")
                printf "  %-24s %s\n", "AuthorizedKeysFile:", ("authorizedkeysfile" in seen ? seen["authorizedkeysfile"] : "default (.ssh/authorized_keys)")
            }
        ' "$RESOLVED_PATH"
    else
        printf '  %-24s %s\n' "sshd_config:" "missing"
    fi

    printf '\nSSH authorized_keys:\n'
    if resolve_source "root/.ssh/authorized_keys"; then
        key_cnt="$(awk '!/^[ \t]*$/ && !/^[ \t]*#/ { c++ } END { print c+0 }' "$RESOLVED_PATH")"
        printf '  %-24s %s\n' "authorized_keys:" "present (${RESOLVED_LAYER}, ${key_cnt} key(s))"
        if [ -n "$SSH_KEY" ]; then
            missing_cnt="$(awk -v existing_file="$RESOLVED_PATH" '
                BEGIN {
                    while ((getline line < existing_file) > 0) {
                        if (line !~ /^[ \t]*$/ && line !~ /^[ \t]*#/) {
                            n = split(line, f, /[ \t]+/)
                            if (n >= 2) {
                                seen[f[1] " " f[2]] = 1
                            }
                        }
                    }
                    close(existing_file)
                }
                $0 !~ /^[ \t]*$/ && $0 !~ /^[ \t]*#/ {
                    if (!(($1 " " $2) in seen)) miss++
                }
                END { print miss + 0 }
            ' "$SSH_KEY")"
            if [ "$missing_cnt" -eq 0 ]; then
                printf '  %-24s %s\n' "Supplied --ssh-key:" "INSTALLED"
            else
                printf '  %-24s %s\n' "Supplied --ssh-key:" "NOT INSTALLED (${missing_cnt} key(s) missing)"
            fi
        fi
    else
        printf '  %-24s %s\n' "authorized_keys:" "${RESOLVED_LAYER:-not present}"
        if [ -n "$SSH_KEY" ]; then
            printf '  %-24s %s\n' "Supplied --ssh-key:" "NOT INSTALLED"
        fi
    fi

    printf '\nFirewall rules (port %s/tcp):\n' "$PORT"
    for fw_rel in etc/iptables/rules.v4 etc/iptables/rules.v6; do
        if resolve_source "$fw_rel"; then
            printf '  %s (%s):\n' "$fw_rel" "$RESOLVED_LAYER"
            check_iptables_status "$RESOLVED_PATH" "$INTERFACES" "$PORT" | while IFS= read -r status_line; do
                printf '    %s\n' "$status_line"
            done
        else
            printf '  %s: not present\n' "$fw_rel"
        fi
    done

    printf '\nProvisioner backups:\n'
    if [ -d "$BACKUP_DIR" ]; then
        printf '  %-24s %s\n' "Backup directory:" "$BACKUP_DIR"
    else
        printf '  %-24s %s\n' "Backup directory:" "none"
    fi
}

run_apply_or_dryrun() {
    init_workdir

    # 1. Install / merge SSH public key into rw/user/root/.ssh/authorized_keys
    cand_auth="${WORK_DIR}/cand_authorized_keys"
    build_authorized_keys_candidate "$cand_auth" "$SSH_KEY"
    write_overlay_file "root/.ssh/authorized_keys" "$cand_auth" "600"

    # 2. Ensure sshd_config allows root key auth on $PORT
    cand_sshd="${WORK_DIR}/cand_sshd_config"
    build_sshd_config_candidate "$cand_sshd" "$PORT"
    write_overlay_file "etc/ssh/sshd_config" "$cand_sshd" "644"

    # 3. Ensure S50sshd is not whited-out and is executable
    upper_s50="${USER_DIR}/etc/init.d/S50sshd"
    if [ -c "$upper_s50" ]; then
        if [ "$MODE" = "dry-run" ]; then
            log "[dry-run] Would remove whiteout $upper_s50"
            CHANGED_COUNT=$((CHANGED_COUNT + 1))
        else
            rm -f "$upper_s50"
            CHANGED_COUNT=$((CHANGED_COUNT + 1))
            log "Removed whiteout $upper_s50"
        fi
    fi
    if resolve_source "etc/init.d/S50sshd"; then
        if [ ! -x "$RESOLVED_PATH" ]; then
            cand_s50="${WORK_DIR}/cand_S50sshd"
            cp "$RESOLVED_PATH" "$cand_s50"
            write_overlay_file "etc/init.d/S50sshd" "$cand_s50" "755"
        fi
    fi

    # 4. Ensure iptables rules.v4 (and rules.v6 unless --no-ipv6) open $PORT on $INTERFACES
    if resolve_source "etc/iptables/rules.v4"; then
        cand_v4="${WORK_DIR}/cand_rules_v4"
        build_iptables_candidate "$RESOLVED_PATH" "$cand_v4" "$INTERFACES" "$PORT"
        write_overlay_file "etc/iptables/rules.v4" "$cand_v4" "644"
    else
        warn "etc/iptables/rules.v4 not found in overlay or lowerdirs; skipping IPv4 firewall update"
    fi

    if [ "$NO_IPV6" -eq 0 ]; then
        if resolve_source "etc/iptables/rules.v6"; then
            cand_v6="${WORK_DIR}/cand_rules_v6"
            build_iptables_candidate "$RESOLVED_PATH" "$cand_v6" "$INTERFACES" "$PORT"
            write_overlay_file "etc/iptables/rules.v6" "$cand_v6" "644"
        fi
    fi

    if [ "$MODE" = "dry-run" ]; then
        if [ "$CHANGED_COUNT" -eq 0 ]; then
            log "[dry-run] Already provisioned; no changes required."
        fi
    else
        if [ "$CHANGED_COUNT" -eq 0 ]; then
            log "Already provisioned; no changes needed."
        else
            log "Provisioning completed successfully (${CHANGED_COUNT} change(s) applied)."
        fi
    fi
}

unmark_provision_file() {
    src="$1"
    out="$2"
    awk '
        BEGIN {
            prefix = "# [beacon_provision] "
            plen = length(prefix)
            in_managed = 0
            count = 0
        }
        {
            if ($0 ~ /^# BEGIN beacon_provision /) {
                in_managed = 1
                next
            }
            if (in_managed) {
                if ($0 ~ /^# END beacon_provision /) {
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
            start = 1
            while (start <= count && lines[start] ~ /^[ \t]*$/) {
                start++
            }
            while (count >= start && lines[count] ~ /^[ \t]*$/) {
                count--
            }
            for (i = start; i <= count; i++) {
                print lines[i]
            }
        }
    ' "$src" > "$out"
}

run_revert() {
    init_workdir
    reverted=0

    _rev_old_ifs="$IFS"
    IFS='
'
    for _rev_rel in $MANAGED_RELPATHS; do
        [ -n "$_rev_rel" ] || continue
        _rev_target="${USER_DIR}/${_rev_rel}"
        _rev_bpath="${BACKUP_DIR}/${_rev_rel}"
        _rev_cpath="${_rev_bpath}.created"

        if [ -f "$_rev_bpath" ]; then
            _rev_staged="${_rev_target}.provision_tmp.$$"
            STAGED_FILES="${STAGED_FILES}
${_rev_staged}"
            ensure_overlay_parent_dirs "$_rev_rel"
            cp -p "$_rev_bpath" "$_rev_staged"
            apply_root_ownership_if_uid0 "$_rev_staged"
            mv "$_rev_staged" "$_rev_target"
            rm -f "$_rev_bpath"
            reverted=$((reverted + 1))
            log "Restored $_rev_target from backup"
        elif [ -f "$_rev_cpath" ]; then
            if [ -e "$_rev_target" ]; then
                rm -f "$_rev_target"
                reverted=$((reverted + 1))
                log "Removed overlay file $_rev_target"
            fi
            rm -f "$_rev_cpath"
        elif file_has_markers "$_rev_target"; then
            _rev_cand="${WORK_DIR}/unmarked_$(printf '%s' "$_rev_rel" | tr '/' '_')"
            unmark_provision_file "$_rev_target" "$_rev_cand"
            _rev_staged="${_rev_target}.provision_tmp.$$"
            STAGED_FILES="${STAGED_FILES}
${_rev_staged}"
            cp -p "$_rev_target" "$_rev_staged"
            cat "$_rev_cand" > "$_rev_staged"
            mv "$_rev_staged" "$_rev_target"
            reverted=$((reverted + 1))
            log "Stripped provision markers from $_rev_target"
        fi
    done
    IFS="$_rev_old_ifs"

    # Remove empty directories created under root/.ssh or backups when empty
    for empty_dir in "${USER_DIR}/root/.ssh" "${USER_DIR}/root" "${USER_DIR}/etc/iptables" "${USER_DIR}/etc/ssh" "${USER_DIR}/etc/init.d" "${USER_DIR}/etc"; do
        [ -d "$empty_dir" ] && rmdir "$empty_dir" 2>/dev/null || true
    done
    if [ -d "$BACKUP_DIR" ]; then
        find "$BACKUP_DIR" -depth -type d -exec rmdir {} ';' 2>/dev/null || true
    fi

    if [ "$reverted" -eq 0 ]; then
        log "Nothing to revert; no provisioner backups or markers found."
    else
        log "Revert completed successfully (${reverted} item(s) reverted)."
    fi
}

case "$MODE" in
    status)
        run_status
        ;;
    dry-run|apply)
        run_apply_or_dryrun
        ;;
    revert)
        run_revert
        ;;
    *)
        die "Unsupported mode: $MODE"
        ;;
esac
