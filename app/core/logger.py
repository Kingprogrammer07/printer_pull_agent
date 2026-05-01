import logging
import sys
from typing import Any


def _configure_stdlib_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )


try:
    import structlog

    _configure_stdlib_logging()
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.processors.format_exc_info,
            structlog.processors.KeyValueRenderer(key_order=["timestamp", "level", "event"]),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    def get_logger(name: str) -> Any:
        return structlog.get_logger(name)

except ImportError:
    _configure_stdlib_logging()

    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

