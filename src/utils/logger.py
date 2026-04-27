"""日志系统：控制台彩色输出 + 文件写入。"""
import sys
import logging
from pathlib import Path
from datetime import datetime

from .config import PROJECT_ROOT, load_config

# 颜色定义
COLORS = {
    "red": "\033[91m",
    "blue": "\033[94m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "cyan": "\033[96m",
    "white": "\033[97m",
    "reset": "\033[0m",
}

ROLE_COLORS = {
    "werewolf": "red",
    "seer": "blue",
    "witch": "cyan",
    "hunter": "yellow",
    "fool": "green",
    "villager": "white",
    "sheriff": "yellow",
    "system": "white",
}

# 日志文件路径（延迟初始化）
_game_log_path: Path | None = None


class ColoredFormatter(logging.Formatter):
    """带颜色角色的日志格式化器。"""

    def format(self, record):
        role = getattr(record, "role", None)
        color_name = ROLE_COLORS.get(role, "white")
        color = COLORS.get(color_name, COLORS["white"])

        level_color = {
            "DEBUG": COLORS["white"],
            "INFO": COLORS["green"],
            "WARNING": COLORS["yellow"],
            "ERROR": COLORS["red"],
        }.get(record.levelname, COLORS["white"])

        timestamp = datetime.now().strftime("%H:%M:%S")
        role_tag = f"[{role}]" if role else ""
        msg = f"{COLORS['white']}{timestamp}{COLORS['reset']} {level_color}{record.levelname:7s}{COLORS['reset']} {color}{role_tag} {record.getMessage()}{COLORS['reset']}"

        return msg


class PlainFormatter(logging.Formatter):
    """无颜色格式化器，用于文件输出。"""

    def format(self, record):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        role = getattr(record, "role", None)
        role_tag = f"[{role}]" if role else ""
        return f"{timestamp} {record.levelname:7s} {role_tag} {record.getMessage()}"


def _init_logger() -> logging.Logger:
    config = load_config()
    log_level = getattr(logging, config.get("output", {}).get("log_level", "INFO"))

    logger = logging.getLogger("ai_werewolf")
    logger.setLevel(log_level)
    logger.handlers.clear()
    logger.propagate = False

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)

    # 文件 handler
    if config.get("output", {}).get("save_log", True):
        global _game_log_path
        log_dir = Path(config.get("output", {}).get("log_dir", "data/game_logs/"))
        abs_log_dir = PROJECT_ROOT / log_dir
        abs_log_dir.mkdir(parents=True, exist_ok=True)
        _game_log_path = abs_log_dir / f"game_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        file_handler = logging.FileHandler(_game_log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(PlainFormatter())
        logger.addHandler(file_handler)

    return logger


# 全局 logger 实例
logger = _init_logger()


def get_logger(name: str = None) -> logging.Logger:
    """获取 logger 实例，按需附加 role 上下文。"""
    return logging.getLogger("ai_werewolf")


def log_with_role(level: int, msg: str, role: str = "system"):
    """以指定角色身份记录日志。"""
    extra = {"role": role}
    logging.getLogger("ai_werewolf").log(level, msg, extra=extra)


def get_game_log_path() -> Path | None:
    """获取当前游戏的日志文件路径。"""
    return _game_log_path
