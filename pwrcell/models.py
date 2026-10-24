import filecmp
import logging
import shutil
import tempfile
from pathlib import Path

from paramiko import AutoAddPolicy, RejectPolicy, SSHClient
from scp import SCPClient

from .config import AppConfig

logger = logging.getLogger(__name__)


def load_models_dir(config: AppConfig) -> Path:
    """Makes the PWRCell Sunspec models available.

    @Return The directory that contains the sunspec files
    """
    repo_root = Path(__file__).resolve().parent.parent
    sunspec_cache_dir = Path(config.sunspec_cache_dir) if config.sunspec_cache_dir else repo_root
    sunspec_models_dir = sunspec_cache_dir / "sunspec-models"
    sunspec_models_dir.mkdir(parents=True, exist_ok=True)

    if not config.pwrcell or not config.pwrcell.ssh_tunnel or not config.pwrcell.ssh_tunnel.host:
        return sunspec_models_dir

    known_hosts_path = sunspec_cache_dir / "known_hosts"
    has_pinned_keys = known_hosts_path.exists() and known_hosts_path.stat().st_size > 0

    with SSHClient() as ssh:
        ssh.load_system_host_keys()
        if has_pinned_keys:
            ssh.load_host_keys(str(known_hosts_path))
            ssh.set_missing_host_key_policy(RejectPolicy())
        else:
            ssh.set_missing_host_key_policy(AutoAddPolicy())

        ssh.connect(
            config.pwrcell.ssh_tunnel.host,
            port=config.pwrcell.ssh_tunnel.port,
            username=config.pwrcell.ssh_tunnel.username,
            key_filename=config.pwrcell.ssh_tunnel.identity_file,
        )
        if not has_pinned_keys:
            try:
                ssh.save_host_keys(str(known_hosts_path))
            except Exception as e:
                logger.debug("Could not save TOFU host keys to %s: %s", known_hosts_path, e)

        logger.info("Checking for new sunspec models on %s", config.pwrcell.ssh_tunnel.host)

        with SCPClient(ssh.get_transport()) as scp:
            remote_version_file = sunspec_models_dir / "version.chk"
            try:
                scp.get(
                    "/opt/pika/sunspec-models/version",
                    str(remote_version_file),
                    preserve_times=True,
                )
                cached_version_file = sunspec_models_dir / "version"
                if cached_version_file.exists() and filecmp.cmp(cached_version_file, remote_version_file):
                    logger.info("Cached sunspec-models are up to date in %s", sunspec_models_dir)
                    logger.info("Version: %s", cached_version_file.read_text())
                else:
                    logger.info("New sunspec-models found, downloading to: %s", sunspec_models_dir)
                    logger.info("Cached Version: %s", cached_version_file.read_text() if cached_version_file.exists() else "n/a")
                    logger.info("Remote Version: %s", remote_version_file.read_text())

                    # Download into a temporary staging directory and atomically replace/merge so interrupted transfers don't corrupt models
                    with tempfile.TemporaryDirectory(dir=str(sunspec_cache_dir)) as stage_dir:
                        scp.get("/opt/pika/sunspec-models", stage_dir, recursive=True, preserve_times=True)
                        staged_models = Path(stage_dir) / "sunspec-models"
                        if staged_models.exists():
                            shutil.copytree(staged_models, sunspec_models_dir, dirs_exist_ok=True)
            finally:
                try:
                    remote_version_file.unlink(missing_ok=True)
                except Exception:
                    pass

    return sunspec_models_dir
