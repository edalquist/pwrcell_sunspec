import filecmp
import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from paramiko import AutoAddPolicy, SSHClient
from scp import SCPClient

from .config import AppConfig

logger = logging.getLogger(__name__)

def load_models_dir(config: AppConfig) -> Path:
  """Makes the PWRCell Sunspec models available.

  @Return The directory that contains the sunspec files
  """
  repo_root = Path(__file__).resolve().parent.parent
  sunspec_cache_dir = Path(config.sunspec_cache_dir) if config.sunspec_cache_dir else repo_root
  sunspec_models_dir = sunspec_cache_dir / 'sunspec-models'
  sunspec_models_dir.mkdir(parents=True, exist_ok=True)

  with SSHClient() as ssh:
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(AutoAddPolicy())

    ssh.connect(config.pwrcell.ssh_tunnel.host,
                port=config.pwrcell.ssh_tunnel.port,
                username=config.pwrcell.ssh_tunnel.username,
                key_filename=config.pwrcell.ssh_tunnel.identity_file)
    logger.info("Checking for new sunspec models on %s", config.pwrcell.ssh_tunnel.host)

    with SCPClient(ssh.get_transport()) as scp:
      remote_version_file = sunspec_models_dir / 'version.chk'
      scp.get('/opt/pika/sunspec-models/version',
              str(remote_version_file),
              preserve_times=True)
      cached_version_file = sunspec_models_dir / 'version'
      if cached_version_file.exists() and filecmp.cmp(cached_version_file, remote_version_file):
        logger.info('Cached sunspec-models are up to date in %s', sunspec_models_dir)
        logger.info('Version: %s', cached_version_file.read_text())
      else:
        logger.info('New sunspec-models found, downloading to: %s', sunspec_models_dir)
        logger.info('Cached Version: %s', cached_version_file.read_text() if cached_version_file.exists() else 'n/a')
        logger.info('Remote Version: %s', remote_version_file.read_text())

        # Recursively download all sunspec model files
        scp.get('/opt/pika/sunspec-models', sunspec_cache_dir, recursive=True, preserve_times=True)

  return sunspec_models_dir