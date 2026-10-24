"""Helper to extract and normalize SSH private keys from Home Assistant add-on options."""

import json
import logging
import os
from pathlib import Path
import re
import sys
from typing import Optional
import yaml

logger = logging.getLogger(__name__)


def normalize_ssh_key(raw_key: str) -> str:
    """Normalize a pasted SSH private key (handling escaped newlines, single-line pastes, etc.)."""
    if not raw_key:
        return ""
    key = raw_key.strip()
    if "\\n" in key:
        key = key.replace("\\n", "\n")
    # Single-line or space-separated key
    m = re.match(r"(-----BEGIN [A-Z0-9 _-]+-----)\s*(.*?)\s*(-----END [A-Z0-9 _-]+-----)", key, re.DOTALL)
    if m:
        header, body, footer = m.groups()
        body_clean = "".join(body.split())
        chunked = "\n".join([body_clean[i : i + 64] for i in range(0, len(body_clean), 64)])
        key = f"{header}\n{chunked}\n{footer}\n"
    elif not key.endswith("\n"):
        key += "\n"
    return key


def setup_ssh_key_from_options(
    options_path: str = "/data/options.json",
    target_key_path: str = "/root/.ssh/id_rsa_pwrcell",
) -> Optional[str]:
    """Extract, normalize, and save SSH key from options.json. Returns key path if saved, else None."""
    p = Path(options_path)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            opts = json.load(f)
    except Exception as e:
        print(f"[ERROR] Could not parse options file {p}: {e}", file=sys.stderr)
        return None

    raw_key = opts.get("ssh_key", "")
    if not raw_key or raw_key == "null":
        return None

    normalized = normalize_ssh_key(raw_key)
    if not normalized:
        return None

    target = Path(target_key_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(normalized)
    print(f"[INFO] Successfully normalized and saved SSH private key to {target} ({len(normalized)} bytes)")
    return str(target)


def generate_config_from_options(
    options_path: str = "/data/options.json",
    config_path: str = "/data/pwrcell.yaml",
    target_key_path: str = "/root/.ssh/id_rsa_pwrcell",
) -> Optional[str]:
    """Generate pwrcell.yaml safely from options.json using yaml.safe_dump with 0600 permissions."""
    p = Path(options_path)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            opts = json.load(f) or {}
    except Exception as e:
        print(f"[ERROR] Could not parse options file {p}: {e}", file=sys.stderr)
        return None

    # First extract/normalize pasted SSH key if present
    saved_key = setup_ssh_key_from_options(options_path=options_path, target_key_path=target_key_path)
    ssh_key_file = opts.get("ssh_key_file") or ""
    if ssh_key_file == "null":
        ssh_key_file = ""

    id_file = ""
    if saved_key and Path(saved_key).exists() and Path(saved_key).stat().st_size > 0:
        id_file = saved_key
    elif Path(target_key_path).exists() and Path(target_key_path).stat().st_size > 0:
        id_file = target_key_path
    elif ssh_key_file and Path(ssh_key_file).exists():
        id_file = ssh_key_file
    elif Path("/share/pwrcell_ssh_key").exists():
        id_file = "/share/pwrcell_ssh_key"

    client_name = opts.get("mqtt_client_name") or ""
    if not client_name or client_name == "null":
        client_name = os.environ.get("HOSTNAME") or "pwrcell-ha"

    cfg_dict = {
        "testing": False,
        "poll_rate": int(opts.get("poll_rate", 12) or 12),
        "config_poll_interval": int(opts.get("config_poll_interval", 45) or 45),
        "slow_poll_interval": int(opts.get("slow_poll_interval", 300) or 300),
        "enable_polling": True,
        "log_level": str(opts.get("log_level") or "INFO"),
        "pwrcell": {
            "ssh_tunnel": {
                "host": str(opts.get("beacon_host") or "192.168.0.73"),
                "port": int(opts.get("beacon_port", 22) or 22),
                "username": str(opts.get("beacon_user") or "root"),
                "identity_file": id_file,
                "password": str(opts.get("beacon_password") or ""),
                "key_passphrase": str(opts.get("ssh_key_passphrase") or ""),
            }
        },
        "mqtt": {
            "client_name": str(client_name),
            "host": str(opts.get("mqtt_host") or "core-mosquitto"),
            "port": int(opts.get("mqtt_port", 1883) or 1883),
            "username": str(opts.get("mqtt_username") or ""),
            "password": str(opts.get("mqtt_password") or ""),
        },
    }

    target_cfg = Path(config_path)
    target_cfg.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target_cfg, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg_dict, f, default_flow_style=False, sort_keys=False)
    print(f"[INFO] Successfully generated {target_cfg}")
    return str(target_cfg)


if __name__ == "__main__":
    opts_file = sys.argv[1] if len(sys.argv) > 1 else "/data/options.json"
    if len(sys.argv) > 2:
        generate_config_from_options(opts_file, sys.argv[2])
    else:
        setup_ssh_key_from_options(opts_file)
