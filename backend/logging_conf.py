"""统一日志：终端 + 文件（按天滚动，保留最近 14 天）。"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler


LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
KEEP_DAYS = 14

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging():
    """配置根 logger，并让 uvicorn/fastapi 的日志统一走这里。

    可以重复调用：会先清掉旧 handler，避免测试或热重载时重复写入。
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
    console = logging.StreamHandler()
    console.setFormatter(formatter)

    file_handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        backupCount=KEEP_DAYS,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"

    root = logging.getLogger()
    for old in root.handlers:
        root.removeHandler(old)
        old.close()
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(file_handler)

    # uvicorn 默认给这三个 logger 挂了它自己的 handler，统一收编到根 logger。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logger = logging.getLogger(name)
        for old in logger.handlers:
            logger.removeHandler(old)
            old.close()
        logger.setLevel(logging.INFO)
        logger.propagate = True

    # httpx 默认每条请求都打 INFO，对我们太吵，只保留 WARNING 以上。
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
