import logging
import filecmp

from contextlib import contextmanager
from paramiko import SSHClient
from scp import SCPClient
from pathlib import Path
from typing import Generator

from pwrcell.config import RootConfig

@contextmanager
def sunspec_models(config: RootConfig) -> Generator[Path, None, None]:
  """Makes the PWRCell Sunspec models available.

  @Return The directory that contains the sunspec files
  """
  sunspec_cache_dir = Path(config.sunspec_cache_dir)
  with SSHClient() as ssh:
    ssh.load_system_host_keys()

    ssh.connect(config.pwrcell.ssh_tunnel.host,
                port=config.pwrcell.ssh_tunnel.port,
                username=config.pwrcell.ssh_tunnel.username,
                key_filename=config.pwrcell.ssh_tunnel.identity_file)
    logging.info("Checking for new sunspec models on %s", config.pwrcell.ssh_tunnel.host)

    with SCPClient(ssh.get_transport()) as scp:
      remote_version_file = sunspec_cache_dir / 'sunspec-models' / 'version.chk'
      scp.get('/opt/pika/sunspec-models/version',
              remote_version_file,
              preserve_times=True)
      cached_version_file = sunspec_cache_dir / 'sunspec-models' / 'version'
      if cached_version_file.exists() and filecmp.cmp(cached_version_file, remote_version_file):
        logging.info('Cached sunspec-models are up to date.')
        logging.info('Version: %s', cached_version_file.read_text())
      else:
        logging.info('New sunspec-models found, downloading...')
        logging.info('Cached Version: %s', cached_version_file.read_text() if cached_version_file.exists() else 'n/a')
        logging.info('Remote Version: %s', remote_version_file.read_text())

        # Recursively download all sunspec model files
        scp.get('/opt/pika/sunspec-models', sunspec_cache_dir, recursive=True, preserve_times=True)

  yield sunspec_cache_dir