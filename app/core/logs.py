import json
import logging
import os
import sys
import time

SKIP = {"/health"}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("method", "path", "status", "ms", "ip"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup(name="app"):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for logger_name in ("uvicorn", "uvicorn.error", "arq", "aiogram"):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    return logging.getLogger(name)


async def request_logger(request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logging.getLogger("app").exception(
            "unhandled error",
            extra={"method": request.method, "path": request.url.path},
        )
        raise
    path = request.url.path
    if path not in SKIP and not path.startswith("/static/"):
        logging.getLogger("app.request").info(
            "request",
            extra={
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000),
                "ip": request.client.host if request.client else "",
            },
        )
    return response
