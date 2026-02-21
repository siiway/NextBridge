import logging
import sys
import os
from datetime import datetime

# ANSI 颜色码
COLORS = {
    'DBG': '\033[36m',   # 青蓝
    'INF': '\033[32m',   # 绿色
    'WRN': '\033[33m',   # 黄色
    'ERR': '\033[31m',   # 红色
    'CRT': '\033[91m\033[1m',  # 亮红加粗
    'RST': '\033[0m'
}

# 是否为终端
IS_TTY = sys.stdout.isatty()

# 日志文件输出目录
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 生成日志文件名：20250915-15031606.log
_log_filename = datetime.now().strftime("%Y%m%d-%H%M%S%f")[:-3] + ".log"  # 毫秒精度
LOG_FILE_PATH = os.path.join(LOG_DIR, _log_filename)


# Sensitive strings to redact from all log output.
# Populated by register_sensitive() after the config is loaded.
_sensitive: set[str] = set()


def register_sensitive(values: frozenset[str]) -> None:
    """Register secret strings that must never appear in log output."""
    _sensitive.clear()
    # Skip values shorter than 8 chars to avoid masking common substrings
    _sensitive.update(v for v in values if len(v) >= 8)


class MaskingFilter(logging.Filter):
    """Redacts sensitive values from every log record before emission."""

    def filter(self, record: logging.LogRecord) -> bool:
        if _sensitive:
            msg = record.getMessage()
            for secret in _sensitive:
                if secret in msg:
                    msg = msg.replace(secret, "***")
            record.msg = msg
            record.args = ()
        return True


class CustomFormatter(logging.Formatter):
    replaces = {
        'DEBUG': '[DBG]',
        'INFO': '[INF]',
        'WARNING': '[WRN]',
        'ERROR': '[ERR]',
        'CRITICAL': '[CRT]'
    }

    def format(self, record):
        timestamp = datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')
        levelname = record.levelname

        # 获取替换后的级别字符串，如 [DBG]
        level = self.replaces.get(levelname, f'[{levelname}]')

        if level.startswith('[') and len(level) >= 4:
            color_key = level[1:4]
        else:
            color_key = levelname.upper()[:3]

        if IS_TTY and color_key in COLORS:
            colored_level = COLORS[color_key] + level + COLORS['RST']
        else:
            colored_level = level

        try:
            file = os.path.relpath(record.pathname)
        except Exception:
            file = record.pathname

        line = record.lineno
        message = record.getMessage()

        return f"{timestamp} {colored_level} | {file}:{line} | {message}"


# 创建主 logger
logger = logging.getLogger('app')
logger.setLevel(logging.DEBUG)
logger.addFilter(MaskingFilter())

# 清除已有 handlers 防止重复
if logger.handlers:
    for handler in logger.handlers:
        handler.close()  # 确保关闭旧处理器
    logger.handlers.clear()
logger.propagate = False

# 添加控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(CustomFormatter())
console_handler.setLevel(logging.INFO)  # 控制台只输出 INFO 及以上
logger.addHandler(console_handler)

# 添加文件处理器（记录所有 DEBUG 及以上日志）
file_handler = logging.FileHandler(LOG_FILE_PATH, encoding='utf-8')
file_formatter = logging.Formatter(
    '[%(asctime)s] [%(levelname)s] | %(filename)s:%(lineno)d | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(file_formatter)
file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别
logger.addHandler(file_handler)


def get_logger(name=None):
    """返回已配置的日志器（当前共享同一实例）"""
    return logger
