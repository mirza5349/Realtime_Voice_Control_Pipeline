import logging


def configure_logging(level: str) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s level=%(levelname)s logger=%(name)s message=%(message)s",
        force=True,
    )
