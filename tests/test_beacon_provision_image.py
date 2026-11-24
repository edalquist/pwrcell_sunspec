"""Unit tests for util/beacon_provision_image.sh across simulated overlayfs layers."""

import base64
import os
import stat
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "util" / "beacon_provision_image.sh"


def _make_ed25519_pubkey(seed_byte: int, comment: str) -> str:
    """Build a valid OpenSSH ed25519 public key line accepted by ssh-keygen -l."""
    key_type = b"ssh-ed25519"
    pub = bytes([seed_byte % 256]) * 32
    wire = (
        struct.pack(">I", len(key_type))
        + key_type
        + struct.pack(">I", len(pub))
        + pub
    )
    b64 = base64.b64encode(wire).decode("ascii")
    return f"ssh-ed25519 {b64} {comment}"


STOCK_KEY = _make_ed25519_pubkey(1, "generac-support@beacon")
USER_KEY = _make_ed25519_pubkey(2, "user@workstation")
SECOND_USER_KEY = _make_ed25519_pubkey(3, "backup@laptop")

STOCK_SSHD_CONFIG = """\
# Stock Beacon sshd_config
PermitRootLogin no
PasswordAuthentication no
AuthorizedKeysFile\t.ssh/authorized_keys
UsePAM yes
Subsystem\tsftp\t/usr/libexec/sftp-server
"""

STOCK_S50SSHD = """\
#!/bin/sh
[ -f /usr/bin/ssh-keygen ] || exit 0
/usr/sbin/sshd
"""

# Realistic Generac Beacon rules.v4 where port 22 ACCEPT was stripped by an OTA
STOCK_RULES_V4_LOCKED = """\
*filter
:INPUT ACCEPT [0:0]
:FORWARD ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
-A INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
-A INPUT -i eth0 -p tcp -m tcp --dport 20117 -j DROP
-A INPUT -i wlan0 -p tcp -m tcp --dport 20117 -j DROP
-A INPUT -i ppp0 -p tcp -m tcp --dport 20117 -j DROP
-A INPUT -i eth0 -p tcp -m tcp --dport 80 -j DROP
-A INPUT -i eth0 -j DROP
-A INPUT -i wlan0 -j DROP
-A INPUT -i ppp0 -j DROP
-A INPUT -i wlan1 -p tcp -m tcp --dport 22 -j ACCEPT
-A INPUT -i wlan1 -j DROP
COMMIT
"""

STOCK_RULES_V6_LOCKED = """\
*filter
:INPUT ACCEPT [0:0]
:FORWARD ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
-A INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
-A INPUT -i eth0 -p tcp -m tcp --dport 20117 -j DROP
-A INPUT -i ppp0 -p tcp -m tcp --dport 20117 -j DROP
-A INPUT -i eth0 -j DROP
-A INPUT -i wlan0 -j DROP
-A INPUT -i ppp0 -j DROP
COMMIT
"""

RULES_V4_ALREADY_OPEN = """\
*filter
:INPUT ACCEPT [0:0]
:FORWARD ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
-A INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
-A INPUT -i eth0 -p tcp -m tcp --dport 20117 -j DROP
-A INPUT -i eth0 -p tcp -m tcp --dport 22 -j ACCEPT
-A INPUT -i wlan0 -p tcp -m tcp --dport 22 -j ACCEPT
-A INPUT -i eth0 -j DROP
-A INPUT -i wlan0 -j DROP
-A INPUT -i ppp0 -j DROP
COMMIT
"""

RULES_V4_EXPLICIT_DROP = """\
*filter
:INPUT ACCEPT [0:0]
:FORWARD ACCEPT [0:0]
:OUTPUT ACCEPT [0:0]
-A INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
-A INPUT -i eth0 -p tcp -m tcp --dport 22 -j DROP
-A INPUT -i wlan0 -p tcp -m tcp --dport 22 -j REJECT
-A INPUT -i eth0 -j DROP
-A INPUT -i wlan0 -j DROP
COMMIT
"""


def _write_mode(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)


class FakeBeaconOverlayEnv:
    """Simulated Beacon overlayfs roots (rw/user + ro SquashFS + pubkey file)."""

    def __init__(self, tmp_dir: str) -> None:
        self.root = Path(tmp_dir)
        self.rw_root = self.root / "rw"
        self.user_dir = self.rw_root / "user"
        self.ro_root = self.root / "ro"
        self.factory_root = self.root / "factory"
        self.key_file = self.root / "user_key.pub"

        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.ro_root.mkdir(parents=True, exist_ok=True)
        self.factory_root.mkdir(parents=True, exist_ok=True)

        _write_mode(self.ro_root / "etc/ssh/sshd_config", STOCK_SSHD_CONFIG, 0o644)
        _write_mode(self.ro_root / "etc/init.d/S50sshd", STOCK_S50SSHD, 0o755)
        _write_mode(self.ro_root / "etc/iptables/rules.v4", STOCK_RULES_V4_LOCKED, 0o644)
        _write_mode(self.ro_root / "etc/iptables/rules.v6", STOCK_RULES_V6_LOCKED, 0o644)
        _write_mode(
            self.ro_root / "root/.ssh/authorized_keys",
            STOCK_KEY + "\n",
            0o600,
        )
        _write_mode(self.key_file, USER_KEY + "\n", 0o644)

    def rw_tree_files(self) -> list[str]:
        return sorted(
            str(p.relative_to(self.user_dir))
            for p in self.user_dir.rglob("*")
            if p.is_file()
        )

    def run(self, args: list[str], with_ro: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [
            "/bin/sh",
            str(SCRIPT_PATH),
            "--rw-root",
            str(self.rw_root),
        ]
        if with_ro:
            cmd.extend(["--ro-root", str(self.ro_root), "--factory-root", str(self.factory_root)])
        cmd.extend(args)
        return subprocess.run(cmd, text=True, capture_output=True)


class TestBeaconProvisionImageScript(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = FakeBeaconOverlayEnv(tmp.name)

    def test_shell_syntax_valid(self) -> None:
        proc = subprocess.run(
            ["/bin/sh", "-n", str(SCRIPT_PATH)], text=True, capture_output=True
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_status_on_stock_image_is_readonly(self) -> None:
        proc = self.env.run(["--status", "--ssh-key", str(self.env.key_file)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("NOT INSTALLED", out)
        self.assertIn("eth0=BLOCKED", out)
        self.assertIn("wlan0=BLOCKED", out)
        self.assertEqual(self.env.rw_tree_files(), [])

    def test_dry_run_makes_no_changes(self) -> None:
        proc = self.env.run(["--dry-run", "--ssh-key", str(self.env.key_file)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[dry-run]", proc.stdout)
        self.assertEqual(self.env.rw_tree_files(), [])

    def test_apply_on_stock_image_and_idempotency(self) -> None:
        proc = self.env.run(["--apply", "--ssh-key", str(self.env.key_file)])
        self.assertEqual(proc.returncode, 0, proc.stderr)

        # Both stock key and user key must be present with strict OpenSSH permissions
        auth_file = self.env.user_dir / "root/.ssh/authorized_keys"
        auth_text = auth_file.read_text(encoding="utf-8")
        self.assertIn(STOCK_KEY, auth_text)
        self.assertIn(USER_KEY, auth_text)
        self.assertEqual(
            stat.S_IMODE((self.env.user_dir / "root/.ssh").stat().st_mode), 0o700
        )
        self.assertEqual(stat.S_IMODE(auth_file.stat().st_mode), 0o600)

        # sshd_config must put permissive directives before commented restrictive lines
        sshd_file = self.env.user_dir / "etc/ssh/sshd_config"
        sshd_text = sshd_file.read_text(encoding="utf-8")
        self.assertIn("Port 22\n", sshd_text)
        self.assertIn("PermitRootLogin prohibit-password\n", sshd_text)
        self.assertIn("PubkeyAuthentication yes\n", sshd_text)
        self.assertIn("# [beacon_provision] PermitRootLogin no", sshd_text)

        # Both rules.v4 and rules.v6 must ACCEPT eth0 & wlan0 on 22 BEFORE -j DROP
        for rel in ("etc/iptables/rules.v4", "etc/iptables/rules.v6"):
            fw_text = (self.env.user_dir / rel).read_text(encoding="utf-8")
            eth_accept = "-A INPUT -i eth0 -p tcp --dport 22 -j ACCEPT"
            wlan_accept = "-A INPUT -i wlan0 -p tcp --dport 22 -j ACCEPT"
            self.assertIn(eth_accept, fw_text)
            self.assertIn(wlan_accept, fw_text)
            self.assertLess(fw_text.index(eth_accept), fw_text.index("-A INPUT -i eth0 -j DROP"))
            self.assertLess(fw_text.index(wlan_accept), fw_text.index("-A INPUT -i wlan0 -j DROP"))
            self.assertNotIn("ppp0 -p tcp --dport 22 -j ACCEPT", fw_text)

        # Second --apply must make zero changes and remain byte-for-byte identical
        snapshot = {p: (self.env.user_dir / p).read_bytes() for p in self.env.rw_tree_files()}
        proc2 = self.env.run(["--apply", "--ssh-key", str(self.env.key_file)])
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertIn("no changes needed", proc2.stdout)
        for p, orig_bytes in snapshot.items():
            self.assertEqual((self.env.user_dir / p).read_bytes(), orig_bytes)

        # Post-apply --status verifies key installed and port 22 OPEN
        proc_st = self.env.run(["--status", "--ssh-key", str(self.env.key_file)])
        self.assertEqual(proc_st.returncode, 0, proc_st.stderr)
        self.assertIn("Supplied --ssh-key:      INSTALLED", proc_st.stdout)
        self.assertIn("eth0=OPEN", proc_st.stdout)
        self.assertIn("wlan0=OPEN", proc_st.stdout)
        self.assertNotIn("BLOCKED", proc_st.stdout)

    def test_apply_on_already_open_firewall_avoids_duplicate_rules(self) -> None:
        _write_mode(
            self.env.ro_root / "etc/iptables/rules.v4", RULES_V4_ALREADY_OPEN, 0o644
        )
        proc = self.env.run(["--apply", "--ssh-key", str(self.env.key_file)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        v4_overlay = self.env.user_dir / "etc/iptables/rules.v4"
        if v4_overlay.exists():
            txt = v4_overlay.read_text(encoding="utf-8")
            self.assertEqual(txt.count("--dport 22 -j ACCEPT"), 2)
        else:
            # rules.v4 was left untouched in lowerdir because both rules already existed
            self.assertFalse(v4_overlay.exists())

    def test_apply_comments_out_explicit_port_22_drop_rules(self) -> None:
        _write_mode(
            self.env.ro_root / "etc/iptables/rules.v4", RULES_V4_EXPLICIT_DROP, 0o644
        )
        proc = self.env.run(["--apply", "--ssh-key", str(self.env.key_file)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        v4_text = (self.env.user_dir / "etc/iptables/rules.v4").read_text(encoding="utf-8")
        self.assertIn(
            "# [beacon_provision] -A INPUT -i eth0 -p tcp -m tcp --dport 22 -j DROP",
            v4_text,
        )
        self.assertIn(
            "# [beacon_provision] -A INPUT -i wlan0 -p tcp -m tcp --dport 22 -j REJECT",
            v4_text,
        )
        self.assertIn("-A INPUT -i eth0 -p tcp --dport 22 -j ACCEPT", v4_text)
        self.assertIn("-A INPUT -i wlan0 -p tcp --dport 22 -j ACCEPT", v4_text)

    def test_custom_port_interfaces_and_no_ipv6(self) -> None:
        proc = self.env.run(
            [
                "--apply",
                "--ssh-key",
                str(self.env.key_file),
                "--port",
                "2222",
                "--interfaces",
                "eth0",
                "--no-ipv6",
            ]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sshd_text = (self.env.user_dir / "etc/ssh/sshd_config").read_text(encoding="utf-8")
        self.assertIn("Port 2222\n", sshd_text)

        v4_text = (self.env.user_dir / "etc/iptables/rules.v4").read_text(encoding="utf-8")
        self.assertIn("-A INPUT -i eth0 -p tcp --dport 2222 -j ACCEPT", v4_text)
        self.assertNotIn("wlan0 -p tcp --dport 2222", v4_text)
        self.assertFalse((self.env.user_dir / "etc/iptables/rules.v6").exists())

    def test_fixes_non_executable_s50sshd(self) -> None:
        os.chmod(self.env.ro_root / "etc/init.d/S50sshd", 0o644)
        proc = self.env.run(["--apply", "--ssh-key", str(self.env.key_file)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        s50_upper = self.env.user_dir / "etc/init.d/S50sshd"
        self.assertTrue(s50_upper.exists())
        self.assertEqual(stat.S_IMODE(s50_upper.stat().st_mode), 0o755)

    def test_revert_removes_created_overlay_files_and_restores_preexisting(self) -> None:
        # Pre-existing overlay authorized_keys with only SECOND_USER_KEY
        preexisting_auth = SECOND_USER_KEY + "\n"
        _write_mode(self.env.user_dir / "root/.ssh/authorized_keys", preexisting_auth, 0o600)

        proc_apply = self.env.run(["--apply", "--ssh-key", str(self.env.key_file)])
        self.assertEqual(proc_apply.returncode, 0, proc_apply.stderr)
        self.assertIn(
            USER_KEY,
            (self.env.user_dir / "root/.ssh/authorized_keys").read_text(encoding="utf-8"),
        )
        self.assertTrue((self.env.user_dir / "etc/ssh/sshd_config").exists())
        self.assertTrue((self.env.user_dir / "etc/iptables/rules.v4").exists())

        proc_rev = self.env.run(["--revert"])
        self.assertEqual(proc_rev.returncode, 0, proc_rev.stderr)

        # Newly created overlay files must be deleted (restoring SquashFS lowerdir passthrough)
        self.assertFalse((self.env.user_dir / "etc/ssh/sshd_config").exists())
        self.assertFalse((self.env.user_dir / "etc/iptables/rules.v4").exists())
        self.assertFalse((self.env.user_dir / "etc/iptables/rules.v6").exists())
        # Pre-existing overlay file must be restored byte-for-byte
        self.assertEqual(
            (self.env.user_dir / "root/.ssh/authorized_keys").read_text(encoding="utf-8"),
            preexisting_auth,
        )

        # Second --revert must be a clean no-op
        proc_rev2 = self.env.run(["--revert"])
        self.assertEqual(proc_rev2.returncode, 0, proc_rev2.stderr)
        self.assertIn("Nothing to revert", proc_rev2.stdout)

    def test_security_and_argument_guards(self) -> None:
        # Reject private keys
        priv_file = self.env.root / "id_ed25519"
        priv_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n", encoding="utf-8")
        proc_priv = self.env.run(["--apply", "--ssh-key", str(priv_file)])
        self.assertNotEqual(proc_priv.returncode, 0)
        self.assertIn("PRIVATE key", proc_priv.stderr)

        # Reject invalid pubkey format
        bad_pub = self.env.root / "bad.pub"
        bad_pub.write_text("not-a-valid-key\n", encoding="utf-8")
        proc_bad = self.env.run(["--apply", "--ssh-key", str(bad_pub)])
        self.assertNotEqual(proc_bad.returncode, 0)

        # Reject invalid ports
        for bad_port in ("0", "70000", "abc"):
            proc_p = self.env.run(
                ["--apply", "--ssh-key", str(self.env.key_file), "--port", bad_port]
            )
            self.assertNotEqual(proc_p.returncode, 0)

        # Reject unsafe interface names
        proc_iface = self.env.run(
            ["--apply", "--ssh-key", str(self.env.key_file), "--interfaces", "eth0;rm"]
        )
        self.assertNotEqual(proc_iface.returncode, 0)

        # Require mode and --ssh-key for --apply
        self.assertNotEqual(self.env.run([]).returncode, 0)
        self.assertNotEqual(self.env.run(["--apply"]).returncode, 0)

        # Reject rw-root missing user/ subdirectory
        with tempfile.TemporaryDirectory() as bad_rw:
            proc_guard = subprocess.run(
                [
                    "/bin/sh",
                    str(SCRIPT_PATH),
                    "--rw-root",
                    bad_rw,
                    "--apply",
                    "--ssh-key",
                    str(self.env.key_file),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc_guard.returncode, 0)
            self.assertIn("user", proc_guard.stderr)


if __name__ == "__main__":
    unittest.main()
