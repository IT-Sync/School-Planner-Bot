import logging
import sys


def configure_logging() -> None:
    """Configure structured logging for the bot."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
