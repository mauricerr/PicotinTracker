from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .cache import DedupeCache
from .config import MonitorConfig, load_env_file
from .monitor import PicotinMonitor, setup_logging
from .notifiers import choose_notifier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one conservative Picotin inventory poll.")
    parser.add_argument("--env", type=Path, default=None, help="Optional .env file path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    config = MonitorConfig.from_env()
    setup_logging(config.log_path)
    cache = DedupeCache(config.cache_path, config.dedupe_hours)
    monitor = PicotinMonitor(config, cache, choose_notifier())
    asyncio.run(monitor.run_once())


if __name__ == "__main__":
    main()
