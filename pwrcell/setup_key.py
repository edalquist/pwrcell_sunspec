"""Helper to extract and normalize SSH private keys from Home Assistant add-on options."""

import json
import logging
import os
from pathlib import Path
import re
import sys
from typing import Optional

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
    with open(target, "w", encoding="utf-8") as f:
        f.write(normalized)
    os.chmod(target, 0o600)
    print(f"[INFO] Successfully normalized and saved SSH private key to {target} ({len(normalized)} bytes)")
    return str(target)


if __name__ == "__main__":
    opts_file = sys.argv[1] if len(sys.argv) > 1 else "/data/options.json"
    setup_ssh_key_from_options(opts_file)
