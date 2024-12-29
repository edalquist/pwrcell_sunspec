
import time
from contextlib import contextmanager
from logging import Logger
from typing import Generator


@contextmanager
def time_fn(logger: Logger, msg, *args) -> Generator[None, None, None]:
  start_t = time.perf_counter_ns()
  yield
  run_t = round((time.perf_counter_ns() - start_t) / 1000, 2)
  args = list(args) + [run_t]
  logger.debug(msg, *args)
