from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    try:
        from typing import TypeIs
    except ImportError:
        from typing import TypeIs


def is_dict_str_obj(val: object) -> TypeIs[dict[str, object]]:
    if not isinstance(val, dict):
        return False
    d = cast("dict[object, object]", val)
    return all(isinstance(k, str) for k in d)


def get_variable_strict(path: str) -> str:
    """Get variable from env; raises ValueError if not found."""
    env_name = path.split("/")[-1]
    val = os.environ.get(env_name)
    if val is None:
        raise ValueError(f"Variable not found: {path} (env: {env_name})")
    return val


def get_resource_strict(path: str) -> dict[str, object]:
    """Resources are not supported without Windmill. Always raises."""
    raise ValueError(f"get_resource_strict: no backend available for: {path}")


def get_variable(path: str) -> str | None:
    """Get variable from env; returns None if not found."""
    env_name = path.split("/")[-1]
    return os.environ.get(env_name)


def get_resource(path: str) -> dict[str, object] | None:
    """Resources are not supported without Windmill."""
    _init_logging().warning("get_resource called but no backend: %s", path)
    return None


def run_script(path: str, args: dict[str, object] | None = None) -> tuple[Exception | None, object]:
    """run_script is not supported without Windmill."""
    err = NotImplementedError(f"run_script: no backend available for: {path}")
    return err, None


_logger: logging.Logger | None = None


def _init_logging() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    logger = logging.getLogger("booking_titanium")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    _logger = logger
    return logger


def log(message: str, **kwargs: object) -> None:
    try:
        logger = _init_logging()
        level = logging.INFO
        msg_upper = message.upper()
        if "ERROR" in msg_upper or "CATASTROPHE" in msg_upper or "FAIL" in msg_upper:
            level = logging.ERROR
        elif "WARN" in msg_upper:
            level = logging.WARNING

        ctx = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        final_msg = f"{message} | {ctx}" if kwargs else message
        logger.log(level, final_msg)
    except Exception:
        pass
