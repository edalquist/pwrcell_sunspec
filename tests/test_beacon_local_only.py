"""Unit tests for util/beacon_local_only.sh against a simulated Beacon filesystem."""

import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "util" / "beacon_local_only.sh"

STOCK_MONIT_CFG = """\
include /opt/pika/etc/monit.d/*.cfg

set daemon 5

set httpd port 2181
    allow 127.0.0.1/32
    allow 10.10.10.0/24

set logfile /var/log/monit.log

check program reboot_trigger with path "/opt/pika/bin/rebooter.sh"
    if status != 0 then alert

check network eth0 with interface eth0
    if failed link for 4 cycles then alert
    group network

check program ntpdate with path "/opt/pika/bin/check_watchdog.sh /tmp/ntpdate-timestamp 14400" every 12 cycles
    if status !=0 then exec "/usr/bin/ntpdate-sync"
    repeat every 1 cycle

check program monit_timestamp with path "/bin/sh -c 'date +%s > /tmp/monit-timestamp'"
    if status != 0 then alert
"""

STOCK_MQTT_CLIENT_CFG = """\
check process mqtt_client with pidfile /var/run/mqtt.pid
    start program = "/opt/pika/etc/init.d/S58statuspusher start"
    stop program = "/opt/pika/etc/init.d/S58statuspusher stop"
    if not exist then restart
    depends on lcm_core

# reboot beacon if MQTT inactive for more than 24 hours
check program mqtt_reboot with path "/opt/pika/bin/check_watchdog.sh /tmp/mqtt_active 1800" every 361 cycles
    if status != 0 for 48 cycles then exec "/sbin/reboot"

# check over 2 cycles to wait for mqtt_client to initialize /tmp/mqtt_active
check program mqtt_active with path "/opt/pika/bin/check_watchdog.sh /tmp/mqtt_active 600" every 61 cycles
    if status != 0 for 2 cycles then exec "/opt/pika/etc/init.d/S58statuspusher stop"
    repeat every 2 cycles
    depends on mqtt_client

# Check for any locked-up IPv6 connections to AWS
check program ipv6_monitor with path "/opt/pika/bin/ipv6_monitor 5" every 60 cycles
    if status !=0 then alert
    depends on mqtt_client
"""

STOCK_CHECK_INTERNET_CFG = """\
# check internet connection every minute and failover to LTE or attempt to recover
check program internet with path "/opt/pika/bin/check_internet.sh" every 12 cycles
    if status !=0 then exec "/bin/echo check_internet failed"
"""

STOCK_LCM_CORE_CFG = """\
check process lcm_core with pidfile /var/run/lcm_core.pid
    restart program = "/opt/pika/etc/init.d/S51lcm restart"
    stop program = "/opt/pika/etc/init.d/S51lcm stop"

check program check_fifos with path /opt/pika/bin/check_fifos.sh
    restart program = "/opt/pika/etc/init.d/S51lcm restart"
    stop program = "/opt/pika/etc/init.d/S51lcm stop"
    if status != 0 then restart
    depends on lcm_core

# maintain /tmp/inet_good so lcm_core can indicate via status update over RCP
check program inet_good with path "/opt/pika/bin/check_inet.sh 120"
    if status != 0 then alert

check program lcm_watchdog with path "/opt/pika/bin/check_watchdog.sh /tmp/lcm_watchdog 10"
    restart program = "/opt/pika/etc/init.d/S51lcm restart"
    if status !=0 for 2 cycles then restart
    depends on lcm_core

check program wifi_trigger with path /opt/pika/bin/wifi_trigger.sh
    if status != 0 then alert
    depends on lcm_core
"""

STOCK_AUTOSSH_CFG = """\
check program autossh_triggers with path "/opt/pika/bin/do_autossh run_triggers"
    with timeout 30 seconds
    if status !=0 then alert

check program sshidle_monitor with path "/opt/pika/bin/sshidle_monitor 43200 3600"
    with timeout 30 seconds
    if status !=0 then alert
    depends on autossh_triggers
"""

STOCK_UPDATE_MANAGER_CFG = """\
check process update_manager with pidfile /var/run/update_manager.pid
    start program = "/opt/pika/etc/init.d/S90update_manager start"
    stop program = "/opt/pika/etc/init.d/S90update_manager stop"
    if not exist then restart
"""

STOCK_MOSQUITTO_REF_CFG = """\
check process mosquitto with pidfile /var/run/mosquitto.pid
    start program = "/etc/init.d/mosquitto start"
    stop program = "/etc/init.d/mosquitto stop"

check program mosquitto_monitor with path "/opt/pika/bin/check_mosquitto_db.sh" every 60 cycles
    if status !=0 then exec "/etc/init.d/mosquitto restart"
    depends on mosquitto
"""

STOCK_MOSQUITTO_CONF = """\
listener 1883 0.0.0.0
connection_messages true
allow_anonymous true
persistence true
persistence_file /opt/pika/var/lib/mosquitto/mosquitto.db
max_queued_bytes 50000000
max_queued_messages 100000
include_dir /tmp/mosquitto
"""

STOCK_NTPDATE_CONF = """\
# Configuration script used by ntpdate-sync script

NPSERVERS="192.168.0.2"
HTPSERVERS="amazonaws.com"

# Set to "yes" to write time to hardware clock on success
UPDATE_HWCLOCK="yes"
"""


def _write_mode(path: Path, content: str | bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)


class FakeBeaconEnv:
    """Simulated REbus Beacon directory tree with mock service binaries."""

    def __init__(self, tmp_dir: str) -> None:
        self.root = Path(tmp_dir)
        self.call_log = self.root / "call_log.txt"
        self.mock_bin = self.root / "mock_bin"
        self.mock_bin.mkdir(parents=True, exist_ok=True)

        self.monit_cfg = self.root / "opt/pika/etc/monit.cfg"
        self.mqtt_client_cfg = self.root / "opt/pika/etc/monit.d/mqtt_client.cfg"
        self.check_internet_cfg = self.root / "opt/pika/etc/monit.d/check_internet.cfg"
        self.lcm_core_cfg = self.root / "opt/pika/etc/monit.d/lcm-core.cfg"
        self.autossh_cfg = self.root / "opt/pika/etc/monit.d/autossh.cfg"
        self.update_manager_cfg = self.root / "opt/pika/etc/monit.d/update_manager.cfg"
        self.mosquitto_monit_cfg = self.root / "opt/pika/etc/monit.d/mosquitto.cfg"
        self.mosquitto_conf = self.root / "etc/mosquitto/mosquitto.conf"
        self.mosquitto_db = self.root / "opt/pika/var/lib/mosquitto/mosquitto.db"
        self.ntpdate_conf = self.root / "etc/default/ntpdate"
        self.ntpdate_stamp = self.root / "tmp/ntpdate-timestamp"
        self.logrotate_dir = self.root / "etc/logrotate.d"
        self.binary_log_logrotate = self.logrotate_dir / "lcm_binary_log"
        self.binary_log = self.root / "var/log/lcm_core/binary_log"
        self.update_mgr_pid = self.root / "var/run/update_manager.pid"
        self.pika_bin_dir = self.root / "opt/pika/bin"
        self.local_mqtt_check_script = self.pika_bin_dir / "check_local_mqtt_live.sh"
        self.cron_hourly_dir = self.root / "etc/cron.hourly"
        self.poller_db_prune_script = self.cron_hourly_dir / "prune_sd_poller_cloud_queue"
        self.sd_poller_db = self.root / "opt/pika/var/lib/sd_poller.db"
        self.sd_poller_pid = self.root / "var/run/sd_poller.pid"
        self.mqtt_pid = self.root / "var/run/mqtt.pid"

        _write_mode(self.monit_cfg, STOCK_MONIT_CFG, 0o700)
        _write_mode(self.mqtt_client_cfg, STOCK_MQTT_CLIENT_CFG, 0o640)
        _write_mode(self.check_internet_cfg, STOCK_CHECK_INTERNET_CFG, 0o644)
        _write_mode(self.lcm_core_cfg, STOCK_LCM_CORE_CFG, 0o640)
        _write_mode(self.autossh_cfg, STOCK_AUTOSSH_CFG, 0o640)
        _write_mode(self.update_manager_cfg, STOCK_UPDATE_MANAGER_CFG, 0o640)
        _write_mode(self.mosquitto_monit_cfg, STOCK_MOSQUITTO_REF_CFG, 0o640)
        _write_mode(self.mosquitto_conf, STOCK_MOSQUITTO_CONF, 0o644)
        _write_mode(self.ntpdate_conf, STOCK_NTPDATE_CONF, 0o644)
        _write_mode(self.mosquitto_db, b"M" * (300 * 1024), 0o600)
        _write_mode(self.update_mgr_pid, "1234\n", 0o644)
        _write_mode(self.sd_poller_pid, "2345\n", 0o644)
        _write_mode(self.mqtt_pid, "3456\n", 0o644)
        self.logrotate_dir.mkdir(parents=True, exist_ok=True)
        self.pika_bin_dir.mkdir(parents=True, exist_ok=True)
        self.cron_hourly_dir.mkdir(parents=True, exist_ok=True)
        self.binary_log.parent.mkdir(parents=True, exist_ok=True)
        with self.binary_log.open("wb") as f:
            f.truncate(105 * 1024 * 1024)
        os.chmod(self.binary_log, 0o644)
        (self.root / "tmp").mkdir(parents=True, exist_ok=True)

        # Populate realistic SQLite sd_poller.db with unsent web_packages bloat
        self.sd_poller_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.sd_poller_db))
        try:
            conn.executescript(
                """
                CREATE TABLE subscriptions (id INTEGER PRIMARY KEY, nickname TEXT UNIQUE);
                CREATE TABLE updates (id INTEGER PRIMARY KEY, bundled INTEGER DEFAULT 0, binary_data BLOB);
                CREATE TABLE web_packages (
                    id INTEGER PRIMARY KEY,
                    created_at INTEGER,
                    sent_to_server INTEGER DEFAULT 0,
                    no_coalesce INTEGER DEFAULT 0,
                    size INTEGER,
                    package_data BLOB
                );
                """
            )
            conn.execute("INSERT INTO subscriptions (id, nickname) VALUES (1, 'legacy_sd')")
            conn.execute("INSERT INTO subscriptions (id, nickname) VALUES (2, 'site_energy')")
            conn.execute("INSERT INTO updates (id, bundled, binary_data) VALUES (1, 0, ?)", (b"u1",))
            conn.execute("INSERT INTO updates (id, bundled, binary_data) VALUES (2, 1, ?)", (b"u2",))
            blob = b"X" * 2048
            for i in range(40):
                conn.execute(
                    "INSERT INTO web_packages (created_at, sent_to_server, no_coalesce, size, package_data) VALUES (?, 0, 0, ?, ?)",
                    (1700000000 + i, len(blob), blob),
                )
            conn.execute(
                "INSERT INTO web_packages (created_at, sent_to_server, no_coalesce, size, package_data) VALUES (?, 1, 0, 10, ?)",
                (1700001000, b"sent_pkg"),
            )
            conn.commit()
        finally:
            conn.close()
        os.chmod(self.sd_poller_db, 0o644)

        self.monit_bin = self.mock_bin / "monit"
        _write_mode(
            self.monit_bin,
            f"""#!/bin/sh
echo "monit $*" >> "{self.call_log}"
if [ "${{FAIL_MONIT_TEST:-0}}" = "1" ] && [ "$1" = "-t" ]; then
    echo "monit syntax error" >&2
    exit 1
fi
if [ "$1" = "-t" ] && grep -q 'check_local_mqtt_live\\.sh' "{self.mqtt_client_cfg}"; then
    if [ ! -x "{self.local_mqtt_check_script}" ]; then
        echo "monit check script missing or not executable: {self.local_mqtt_check_script}" >&2
        exit 1
    fi
fi
if [ "$1" = "reload" ] && [ -e "{self.local_mqtt_check_script}" ]; then
    echo "check_local_mqtt_live_present_during_monit_reload" >> "{self.call_log}"
fi
exit 0
""",
            0o755,
        )

        self.mosquitto_init = self.root / "etc/init.d/mosquitto"
        _write_mode(
            self.mosquitto_init,
            f"""#!/bin/sh
echo "mosquitto $*" >> "{self.call_log}"
if [ "${{FAIL_MOSQUITTO_START:-0}}" = "1" ] && [ "$1" = "start" ]; then
    echo "mosquitto start failed" >&2
    exit 1
fi
exit 0
""",
            0o755,
        )

        self.ntpdate_sync = self.root / "usr/bin/ntpdate-sync"
        _write_mode(
            self.ntpdate_sync,
            f"""#!/bin/sh
echo "ntpdate-sync $*" >> "{self.call_log}"
date +%s > "{self.ntpdate_stamp}"
exit 0
""",
            0o755,
        )

        self.update_mgr_init = self.root / "opt/pika/etc/init.d/S90update_manager"
        _write_mode(
            self.update_mgr_init,
            f"""#!/bin/sh
echo "S90update_manager $*" >> "{self.call_log}"
if [ "$1" = "stop" ]; then
    rm -f "{self.update_mgr_pid}"
fi
exit 0
""",
            0o755,
        )

        self.statuspusher_init = self.root / "opt/pika/etc/init.d/S58statuspusher"
        _write_mode(
            self.statuspusher_init,
            f"""#!/bin/sh
echo "S58statuspusher $*" >> "{self.call_log}"
if [ "$1" = "stop" ]; then
    rm -f "{self.mqtt_pid}"
elif [ "$1" = "start" ]; then
    echo "3456" > "{self.mqtt_pid}"
fi
exit 0
""",
            0o755,
        )

        self.statuspoller_init = self.root / "opt/pika/etc/init.d/S57statuspoller"
        _write_mode(
            self.statuspoller_init,
            f"""#!/bin/sh
echo "S57statuspoller $*" >> "{self.call_log}"
if [ "$1" = "stop" ]; then
    rm -f "{self.sd_poller_pid}"
elif [ "$1" = "start" ]; then
    echo "2345" > "{self.sd_poller_pid}"
fi
exit 0
""",
            0o755,
        )

        self.mosquitto_sub_bin = self.mock_bin / "mosquitto_sub"
        _write_mode(
            self.mosquitto_sub_bin,
            """#!/bin/sh
if [ "${MOCK_MQTT_SILENT:-0}" = "1" ]; then
    exit 0
fi
printf 'FAKE_ENERGY_RECORDSET_PAYLOAD'
exit 0
""",
            0o755,
        )

        self.sqlite3_bin = self.mock_bin / "sqlite3"
        _write_mode(
            self.sqlite3_bin,
            f"""#!{sys.executable}
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1], isolation_level=None)
try:
    for stmt in sys.argv[2].split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        cur = conn.execute(stmt)
        if cur.description:
            for row in cur.fetchall():
                print("|".join(str(col) for col in row))
finally:
    conn.close()
""",
            0o755,
        )

    def stock_snapshot(self) -> dict[Path, str]:
        paths = [
            self.monit_cfg,
            self.mqtt_client_cfg,
            self.check_internet_cfg,
            self.lcm_core_cfg,
            self.autossh_cfg,
            self.update_manager_cfg,
            self.mosquitto_monit_cfg,
            self.mosquitto_conf,
            self.ntpdate_conf,
        ]
        return {p: p.read_text(encoding="utf-8") for p in paths}

    def read_calls(self) -> list[str]:
        if not self.call_log.exists():
            return []
        return [
            line for line in self.call_log.read_text(encoding="utf-8").splitlines() if line
        ]

    def clear_calls(self) -> None:
        if self.call_log.exists():
            self.call_log.unlink()

    def poller_db_counts(self) -> tuple[int, int, int, int]:
        conn = sqlite3.connect(str(self.sd_poller_db))
        try:
            subs = conn.execute("SELECT count(*) FROM subscriptions").fetchone()[0]
            updates = conn.execute("SELECT count(*) FROM updates").fetchone()[0]
            unsent = conn.execute(
                "SELECT count(*) FROM web_packages WHERE sent_to_server=0"
            ).fetchone()[0]
            sent = conn.execute(
                "SELECT count(*) FROM web_packages WHERE sent_to_server=1"
            ).fetchone()[0]
            return subs, updates, unsent, sent
        finally:
            conn.close()

    def run(
        self,
        args: list[str],
        extra_env: dict[str, str] | None = None,
        stdin_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["MONIT_BIN"] = str(self.monit_bin)
        env["MOSQUITTO_INIT"] = str(self.mosquitto_init)
        env["NTPDATE_SYNC_BIN"] = str(self.ntpdate_sync)
        env["UPDATE_MGR_INIT"] = str(self.update_mgr_init)
        env["STATUSPUSHER_INIT"] = str(self.statuspusher_init)
        env["STATUSPOLLER_INIT"] = str(self.statuspoller_init)
        env["MOSQUITTO_SUB_BIN"] = str(self.mosquitto_sub_bin)
        env["SQLITE3_BIN"] = str(self.sqlite3_bin)
        env["SD_POLLER_DB_VACUUM_BYTES"] = "8192"
        if extra_env:
            env.update(extra_env)
        if stdin_text is not None:
            cmd = ["/bin/sh", "-s", "--", "--root", str(self.root), *args]
            return subprocess.run(
                cmd,
                input=stdin_text,
                text=True,
                capture_output=True,
                env=env,
            )
        cmd = ["/bin/sh", str(SCRIPT_PATH), "--root", str(self.root), *args]
        return subprocess.run(cmd, text=True, capture_output=True, env=env)


class TestBeaconLocalOnlyScript(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.beacon = FakeBeaconEnv(tmp.name)

    def test_shell_syntax_valid(self) -> None:
        proc = subprocess.run(
            ["/bin/sh", "-n", str(SCRIPT_PATH)], text=True, capture_output=True
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_status_on_stock_beacon_is_readonly_and_detects_issues(self) -> None:
        before = self.beacon.stock_snapshot()
        before_counts = self.beacon.poller_db_counts()
        proc = self.beacon.run(["--status"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("mqtt_reboot:", out)
        self.assertIn("local_mqtt_live:", out)
        self.assertIn("ACTIVE", out)
        self.assertIn("mosquitto.db:", out)
        self.assertIn("WARNING: exceeds 200 kB threshold", out)
        self.assertIn("local/energy_recordset_live: LIVE (", out)
        self.assertIn("NPSERVERS typo:", out)
        self.assertIn("DETECTED", out)
        self.assertIn("binary_log logrotate:", out)
        self.assertIn("not configured", out)
        self.assertIn("105 MiB (WARNING: >= 100 MiB", out)
        self.assertIn("sd_poller.db cron prune: not configured", out)
        self.assertIn("sd_poller.db:", out)
        self.assertIn("40 unsent web_packages", out)
        self.assertEqual(self.beacon.stock_snapshot(), before)
        self.assertEqual(self.beacon.poller_db_counts(), before_counts)
        self.assertEqual(self.beacon.binary_log.stat().st_size, 105 * 1024 * 1024)
        self.assertEqual(self.beacon.read_calls(), [])

        proc_silent = self.beacon.run(["--status"], extra_env={"MOCK_MQTT_SILENT": "1"})
        self.assertEqual(proc_silent.returncode, 0, proc_silent.stderr)
        self.assertIn("local/energy_recordset_live: SILENT (", proc_silent.stdout)

    def test_dry_run_makes_no_changes(self) -> None:
        before = self.beacon.stock_snapshot()
        before_counts = self.beacon.poller_db_counts()
        before_db_size = self.beacon.sd_poller_db.stat().st_size
        proc = self.beacon.run(["--dry-run", "--ntp-server", "192.168.0.2"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[dry-run]", proc.stdout)
        self.assertIn("Would create", proc.stdout)
        self.assertIn("Would truncate", proc.stdout)
        self.assertIn("prune 40 unsent web_packages, VACUUM", proc.stdout)
        self.assertEqual(self.beacon.stock_snapshot(), before)
        self.assertTrue(self.beacon.mosquitto_db.exists())
        self.assertFalse(self.beacon.binary_log_logrotate.exists())
        self.assertFalse(self.beacon.local_mqtt_check_script.exists())
        self.assertFalse(self.beacon.poller_db_prune_script.exists())
        self.assertEqual(self.beacon.poller_db_counts(), before_counts)
        self.assertEqual(self.beacon.sd_poller_db.stat().st_size, before_db_size)
        self.assertEqual(self.beacon.binary_log.stat().st_size, 105 * 1024 * 1024)
        self.assertEqual(self.beacon.read_calls(), [])

    def test_apply_and_idempotency(self) -> None:
        orig_ino = self.beacon.binary_log.stat().st_ino
        orig_db_size = self.beacon.sd_poller_db.stat().st_size
        proc = self.beacon.run(["--apply", "--ntp-server", "192.168.0.2"])
        self.assertEqual(proc.returncode, 0, proc.stderr)

        # local_mqtt_live script created executable and wired into mqtt_client.cfg
        self.assertTrue(self.beacon.local_mqtt_check_script.exists())
        self.assertEqual(
            stat.S_IMODE(self.beacon.local_mqtt_check_script.stat().st_mode), 0o755
        )
        self.assertIn(
            "# Managed by beacon_local_only.sh",
            self.beacon.local_mqtt_check_script.read_text(encoding="utf-8"),
        )

        # Essential local checks remain active
        mqtt_cfg = self.beacon.mqtt_client_cfg.read_text(encoding="utf-8")
        self.assertIn("\ncheck process mqtt_client ", "\n" + mqtt_cfg)
        self.assertIn("\ncheck program local_mqtt_live ", "\n" + mqtt_cfg)
        self.assertIn(
            'with path "/opt/pika/bin/check_local_mqtt_live.sh 15" timeout 30 seconds every 12 cycles',
            mqtt_cfg,
        )
        self.assertIn("# [beacon_local_only] check program mqtt_reboot ", mqtt_cfg)
        self.assertIn("# [beacon_local_only] check program mqtt_active ", mqtt_cfg)
        self.assertIn("# [beacon_local_only] check program ipv6_monitor ", mqtt_cfg)

        lcm_cfg = self.beacon.lcm_core_cfg.read_text(encoding="utf-8")
        self.assertIn("\ncheck process lcm_core ", "\n" + lcm_cfg)
        self.assertIn("\ncheck program lcm_watchdog ", "\n" + lcm_cfg)
        self.assertIn("# [beacon_local_only] check program inet_good ", lcm_cfg)

        chk_cfg = self.beacon.check_internet_cfg.read_text(encoding="utf-8")
        self.assertIn("# [beacon_local_only] check program internet ", chk_cfg)

        autossh_cfg = self.beacon.autossh_cfg.read_text(encoding="utf-8")
        self.assertIn("# [beacon_local_only] check program autossh_triggers ", autossh_cfg)
        self.assertIn("# [beacon_local_only] check program sshidle_monitor ", autossh_cfg)

        upd_cfg = self.beacon.update_manager_cfg.read_text(encoding="utf-8")
        self.assertIn("# [beacon_local_only] check process update_manager ", upd_cfg)

        # Mosquitto AWS bridges disabled and DB deleted
        mosq_conf = self.beacon.mosquitto_conf.read_text(encoding="utf-8")
        self.assertIn("listener 1883 0.0.0.0", mosq_conf)
        self.assertIn("# [beacon_local_only] include_dir /tmp/mosquitto", mosq_conf)
        self.assertIn("# [beacon_local_only] persistence true", mosq_conf)
        self.assertIn("persistence false", mosq_conf)
        self.assertFalse(self.beacon.mosquitto_db.exists())

        # NTP typo fixed
        ntp_conf = self.beacon.ntpdate_conf.read_text(encoding="utf-8")
        self.assertIn('# [beacon_local_only] NPSERVERS="192.168.0.2"', ntp_conf)
        self.assertIn('NTPSERVERS="192.168.0.2"', ntp_conf)
        self.assertIn('HTPSERVERS=""', ntp_conf)
        self.assertTrue(self.beacon.ntpdate_stamp.exists())

        # binary_log logrotate configured and truncated in place (same inode)
        self.assertTrue(self.beacon.binary_log_logrotate.exists())
        lr_conf = self.beacon.binary_log_logrotate.read_text(encoding="utf-8")
        self.assertIn("copytruncate", lr_conf)
        self.assertIn("size 10M", lr_conf)
        self.assertIn("rotate 5", lr_conf)
        self.assertEqual(
            stat.S_IMODE(self.beacon.binary_log_logrotate.stat().st_mode), 0o644
        )
        self.assertEqual(self.beacon.binary_log.stat().st_size, 0)
        self.assertEqual(self.beacon.binary_log.stat().st_ino, orig_ino)

        # sd_poller.db cron prune script installed and DB compacted without losing non-cloud data
        self.assertTrue(self.beacon.poller_db_prune_script.exists())
        self.assertEqual(
            stat.S_IMODE(self.beacon.poller_db_prune_script.stat().st_mode), 0o755
        )
        subs, updates, unsent, sent = self.beacon.poller_db_counts()
        self.assertEqual(subs, 2)
        self.assertEqual(updates, 2)
        self.assertEqual(unsent, 0)
        self.assertEqual(sent, 1)
        self.assertLess(self.beacon.sd_poller_db.stat().st_size, orig_db_size)

        # File permissions preserved
        self.assertEqual(stat.S_IMODE(self.beacon.monit_cfg.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.beacon.mqtt_client_cfg.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.beacon.check_internet_cfg.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(self.beacon.mosquitto_conf.stat().st_mode), 0o644)

        # monit -t strictly precedes monit reload, mosquitto unmonitored/re-monitored,
        # and poller/pusher stopped/restarted cleanly
        calls = self.beacon.read_calls()
        self.assertIn("monit -t", calls)
        self.assertIn("monit reload", calls)
        self.assertLess(calls.index("monit -t"), calls.index("monit reload"))
        self.assertIn("S90update_manager stop", calls)
        self.assertIn("monit unmonitor mosquitto", calls)
        self.assertIn("mosquitto stop", calls)
        self.assertIn("mosquitto start", calls)
        self.assertIn("monit monitor mosquitto", calls)
        self.assertLess(calls.index("monit unmonitor mosquitto"), calls.index("mosquitto stop"))
        self.assertLess(calls.index("mosquitto stop"), calls.index("mosquitto start"))
        self.assertLess(calls.index("mosquitto start"), calls.index("monit monitor mosquitto"))
        self.assertIn("S57statuspoller stop", calls)
        self.assertIn("S57statuspoller start", calls)
        self.assertLess(calls.index("S57statuspoller stop"), calls.index("S57statuspoller start"))
        self.assertIn("S58statuspusher stop", calls)
        self.assertIn("S58statuspusher start", calls)
        self.assertLess(calls.index("S58statuspusher stop"), calls.index("S58statuspusher start"))
        self.assertIn("ntpdate-sync foreground", calls)

        # Second --apply must be a complete byte-for-byte no-op
        first_snapshot = self.beacon.stock_snapshot()
        self.beacon.clear_calls()
        proc2 = self.beacon.run(["--apply", "--ntp-server", "192.168.0.2"])
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertEqual(self.beacon.stock_snapshot(), first_snapshot)
        self.assertEqual(self.beacon.read_calls(), [])

        # Post-apply --status reflects hardened state
        proc_status = self.beacon.run(["--status"])
        self.assertEqual(proc_status.returncode, 0, proc_status.stderr)
        self.assertIn("disabled (by beacon_local_only)", proc_status.stdout)
        self.assertRegex(proc_status.stdout, r"local_mqtt_live:\s+ACTIVE")
        self.assertIn("local/energy_recordset_live: LIVE (", proc_status.stdout)
        self.assertNotIn("DETECTED", proc_status.stdout)
        self.assertIn("not present", proc_status.stdout)
        self.assertIn("managed (", proc_status.stdout)
        self.assertIn("0 MiB", proc_status.stdout)
        self.assertIn("0 unsent web_packages", proc_status.stdout)

    def test_check_local_mqtt_live_script_behavior(self) -> None:
        proc_apply = self.beacon.run(["--apply", "--ntp-server", "192.168.0.2"])
        self.assertEqual(proc_apply.returncode, 0, proc_apply.stderr)

        env = os.environ.copy()
        env["MOSQUITTO_SUB_BIN"] = str(self.beacon.mosquitto_sub_bin)

        env["MOCK_MQTT_SILENT"] = "0"
        proc_live = subprocess.run(
            ["/bin/sh", str(self.beacon.local_mqtt_check_script), "5"],
            text=True,
            capture_output=True,
            env=env,
        )
        self.assertEqual(proc_live.returncode, 0, proc_live.stderr)

        env["MOCK_MQTT_SILENT"] = "1"
        proc_silent = subprocess.run(
            ["/bin/sh", str(self.beacon.local_mqtt_check_script), "5"],
            text=True,
            capture_output=True,
            env=env,
        )
        self.assertEqual(proc_silent.returncode, 1)
        self.assertIn("No local MQTT payload received", proc_silent.stdout)

    def test_silent_local_mqtt_triggers_statuspusher_restart(self) -> None:
        proc1 = self.beacon.run(["--apply", "--ntp-server", "192.168.0.2"])
        self.assertEqual(proc1.returncode, 0, proc1.stderr)

        self.beacon.clear_calls()
        proc2 = self.beacon.run(
            ["--apply", "--ntp-server", "192.168.0.2"],
            extra_env={"MOCK_MQTT_SILENT": "1"},
        )
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        calls = self.beacon.read_calls()
        self.assertIn("monit unmonitor mqtt_client", calls)
        self.assertIn("S58statuspusher stop", calls)
        self.assertIn("S58statuspusher start", calls)
        self.assertIn("monit monitor mqtt_client", calls)
        self.assertIn("monit monitor local_mqtt_live", calls)
        self.assertLess(calls.index("monit unmonitor mqtt_client"), calls.index("S58statuspusher stop"))
        self.assertLess(calls.index("S58statuspusher stop"), calls.index("S58statuspusher start"))
        self.assertLess(calls.index("S58statuspusher start"), calls.index("monit monitor mqtt_client"))
        self.assertLess(calls.index("monit monitor mqtt_client"), calls.index("monit monitor local_mqtt_live"))

    def test_mosquitto_restart_triggers_statuspusher_restart_when_poller_db_kept(self) -> None:
        before_counts = self.beacon.poller_db_counts()
        proc = self.beacon.run(["--apply", "--ntp-server", "192.168.0.2", "--keep-poller-db"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.beacon.poller_db_prune_script.exists())
        self.assertEqual(self.beacon.poller_db_counts(), before_counts)
        calls = self.beacon.read_calls()
        self.assertNotIn("S57statuspoller stop", calls)
        self.assertIn("mosquitto start", calls)
        self.assertIn("S58statuspusher stop", calls)
        self.assertIn("S58statuspusher start", calls)
        self.assertLess(calls.index("mosquitto start"), calls.index("S58statuspusher stop"))
        self.assertLess(calls.index("S58statuspusher stop"), calls.index("S58statuspusher start"))

    def test_disable_ntp_and_switch_to_ntp_server(self) -> None:
        proc1 = self.beacon.run(["--apply", "--disable-ntp"])
        self.assertEqual(proc1.returncode, 0, proc1.stderr)
        monit_cfg_disabled = self.beacon.monit_cfg.read_text(encoding="utf-8")
        self.assertIn("# [beacon_local_only] check program ntpdate ", monit_cfg_disabled)
        self.assertIn(
            '# [beacon_local_only]     if status !=0 then exec "/usr/bin/ntpdate-sync"',
            monit_cfg_disabled,
        )
        # Neighboring check_program must remain untouched
        self.assertIn("\ncheck program monit_timestamp ", monit_cfg_disabled)

        # Switching back to --ntp-server must uncomment ntpdate in monit.cfg
        self.beacon.clear_calls()
        proc2 = self.beacon.run(["--apply", "--ntp-server", "192.168.0.2"])
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        monit_cfg_reenabled = self.beacon.monit_cfg.read_text(encoding="utf-8")
        self.assertIn("\ncheck program ntpdate ", monit_cfg_reenabled)
        self.assertNotIn("# [beacon_local_only] check program ntpdate", monit_cfg_reenabled)
        self.assertIn('NTPSERVERS="192.168.0.2"', self.beacon.ntpdate_conf.read_text(encoding="utf-8"))

    def test_keep_flags_skip_optional_sections(self) -> None:
        before_counts = self.beacon.poller_db_counts()
        proc = self.beacon.run(
            [
                "--apply",
                "--keep-cloud-bridges",
                "--keep-cloud-services",
                "--keep-binary-log",
                "--keep-poller-db",
            ]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.beacon.mosquitto_conf.read_text(encoding="utf-8"), STOCK_MOSQUITTO_CONF)
        self.assertTrue(self.beacon.mosquitto_db.exists())
        self.assertEqual(self.beacon.autossh_cfg.read_text(encoding="utf-8"), STOCK_AUTOSSH_CFG)
        self.assertEqual(
            self.beacon.update_manager_cfg.read_text(encoding="utf-8"),
            STOCK_UPDATE_MANAGER_CFG,
        )
        self.assertFalse(self.beacon.binary_log_logrotate.exists())
        self.assertEqual(self.beacon.binary_log.stat().st_size, 105 * 1024 * 1024)
        self.assertFalse(self.beacon.poller_db_prune_script.exists())
        self.assertEqual(self.beacon.poller_db_counts(), before_counts)
        # Core cloud checks disabled and local_mqtt_live installed
        mqtt_cfg = self.beacon.mqtt_client_cfg.read_text(encoding="utf-8")
        self.assertIn("# [beacon_local_only] check program mqtt_reboot ", mqtt_cfg)
        self.assertIn("\ncheck program local_mqtt_live ", "\n" + mqtt_cfg)
        self.assertTrue(self.beacon.local_mqtt_check_script.exists())
        self.assertIn(
            "# [beacon_local_only] check program internet ",
            self.beacon.check_internet_cfg.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "# [beacon_local_only] check program inet_good ",
            self.beacon.lcm_core_cfg.read_text(encoding="utf-8"),
        )

    def test_small_binary_log_is_not_truncated(self) -> None:
        small_bytes = b"A" * (5 * 1024 * 1024)
        _write_mode(self.beacon.binary_log, small_bytes, 0o644)
        proc = self.beacon.run(["--apply", "--ntp-server", "192.168.0.2"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.beacon.binary_log_logrotate.exists())
        self.assertEqual(self.beacon.binary_log.stat().st_size, len(small_bytes))

    def test_monit_validation_failure_rolls_back(self) -> None:
        before = self.beacon.stock_snapshot()
        proc = self.beacon.run(
            ["--apply", "--ntp-server", "192.168.0.2"],
            extra_env={"FAIL_MONIT_TEST": "1"},
        )
        self.assertNotEqual(proc.returncode, 0)
        # Every monit file must be rolled back to exact pre-run contents
        for monit_file in (
            self.beacon.monit_cfg,
            self.beacon.mqtt_client_cfg,
            self.beacon.check_internet_cfg,
            self.beacon.lcm_core_cfg,
            self.beacon.autossh_cfg,
            self.beacon.update_manager_cfg,
        ):
            self.assertEqual(monit_file.read_text(encoding="utf-8"), before[monit_file])
        self.assertFalse(self.beacon.local_mqtt_check_script.exists())
        self.assertFalse(self.beacon.poller_db_prune_script.exists())
        calls = self.beacon.read_calls()
        self.assertIn("monit -t", calls)
        self.assertNotIn("monit reload", calls)

    def test_mosquitto_start_failure_rolls_back(self) -> None:
        proc = self.beacon.run(
            ["--apply", "--ntp-server", "192.168.0.2"],
            extra_env={"FAIL_MOSQUITTO_START": "1"},
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(
            self.beacon.mosquitto_conf.read_text(encoding="utf-8"), STOCK_MOSQUITTO_CONF
        )
        calls = self.beacon.read_calls()
        self.assertIn("monit monitor mosquitto", calls)

    def test_revert_restores_stock_and_is_idempotent(self) -> None:
        stock = self.beacon.stock_snapshot()
        proc_apply = self.beacon.run(["--apply", "--ntp-server", "192.168.0.2"])
        self.assertEqual(proc_apply.returncode, 0, proc_apply.stderr)

        self.beacon.clear_calls()
        proc_rev = self.beacon.run(["--revert"])
        self.assertEqual(proc_rev.returncode, 0, proc_rev.stderr)
        self.assertEqual(self.beacon.stock_snapshot(), stock)
        self.assertFalse(self.beacon.binary_log_logrotate.exists())
        self.assertFalse(self.beacon.local_mqtt_check_script.exists())
        self.assertFalse(self.beacon.poller_db_prune_script.exists())

        self.assertEqual(stat.S_IMODE(self.beacon.monit_cfg.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.beacon.mqtt_client_cfg.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.beacon.mosquitto_conf.stat().st_mode), 0o644)

        calls = self.beacon.read_calls()
        self.assertIn("monit -t", calls)
        self.assertIn("monit reload", calls)
        self.assertIn("check_local_mqtt_live_present_during_monit_reload", calls)
        self.assertLess(calls.index("monit -t"), calls.index("monit reload"))
        self.assertIn("monit unmonitor mosquitto", calls)
        self.assertIn("mosquitto restart", calls)
        self.assertIn("monit monitor mosquitto", calls)
        self.assertLess(calls.index("monit unmonitor mosquitto"), calls.index("mosquitto restart"))
        self.assertLess(calls.index("mosquitto restart"), calls.index("monit monitor mosquitto"))

        # Second --revert must be a complete no-op
        self.beacon.clear_calls()
        proc_rev2 = self.beacon.run(["--revert"])
        self.assertEqual(proc_rev2.returncode, 0, proc_rev2.stderr)
        self.assertEqual(self.beacon.stock_snapshot(), stock)
        self.assertEqual(self.beacon.read_calls(), [])

    def test_piped_stdin_execution(self) -> None:
        script_body = SCRIPT_PATH.read_text(encoding="utf-8")
        proc = self.beacon.run(
            ["--apply", "--ntp-server", "192.168.0.2"],
            stdin_text=script_body,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(
            "# [beacon_local_only] check program mqtt_reboot ",
            self.beacon.mqtt_client_cfg.read_text(encoding="utf-8"),
        )
        self.assertIn(
            'NTPSERVERS="192.168.0.2"',
            self.beacon.ntpdate_conf.read_text(encoding="utf-8"),
        )

    def test_invalid_arguments_and_non_beacon_guard(self) -> None:
        # Missing mode
        proc_nomode = self.beacon.run([])
        self.assertNotEqual(proc_nomode.returncode, 0)

        # Mutually exclusive NTP flags
        proc_conflict = self.beacon.run(
            ["--apply", "--ntp-server", "192.168.0.2", "--disable-ntp"]
        )
        self.assertNotEqual(proc_conflict.returncode, 0)

        # Unsafe characters in NTP server
        proc_bad_ntp = self.beacon.run(["--apply", "--ntp-server", "192.168.0.2;reboot"])
        self.assertNotEqual(proc_bad_ntp.returncode, 0)

        proc_backslash_ntp = self.beacon.run(["--apply", "--ntp-server", "192.168.0.2\\x"])
        self.assertNotEqual(proc_backslash_ntp.returncode, 0)

        proc_empty_ntp = self.beacon.run(["--apply", "--ntp-server", "   "])
        self.assertNotEqual(proc_empty_ntp.returncode, 0)

        # Non-Beacon directory guard
        with tempfile.TemporaryDirectory() as empty_dir:
            proc_guard = subprocess.run(
                ["/bin/sh", str(SCRIPT_PATH), "--root", empty_dir, "--apply"],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc_guard.returncode, 0)
            self.assertIn("Generac REbus Beacon", proc_guard.stderr)


if __name__ == "__main__":
    unittest.main()
