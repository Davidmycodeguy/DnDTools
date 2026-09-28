"""Starter data shipped with releases: market history (seller names removed) and trained price models,
so a new install prices items from the first minute instead of after hours of crawling."""
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

STARTER_FILES = ("market_history.sqlite", "worth_model.json", "market_model.json")


def install_starter_data(bundle_dir, data_dir):
    """Copy each starter file the user doesn't have yet from `bundle_dir` into `data_dir`; never
    overwrites the user's own data. Returns the names copied."""
    bundle_dir, data_dir = Path(bundle_dir), Path(data_dir)
    if not bundle_dir.is_dir():
        return []
    copied = []
    for name in STARTER_FILES:
        source, target = bundle_dir / name, data_dir / name
        if source.is_file() and not target.exists():
            data_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(name)
    if copied:
        logger.info("Installed starter data: %s", ", ".join(copied))
    return copied
