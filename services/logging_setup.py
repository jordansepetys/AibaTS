from loguru import logger
from pathlib import Path


def setup_logging(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "app.log"

    # Remove default handler to avoid duplicate logs if called twice
    logger.remove()
    logger.add(
        log_path,
        rotation="10 MB",
        retention=10,
        backtrace=True,
        diagnose=False,
        level="INFO",
        enqueue=True,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} - {message}",
    )
    # Also log to stderr during development
    logger.add(
        lambda msg: print(msg, end=""),
        level="INFO",
    )



