from __future__ import annotations

import logging
import os

import uvicorn


def main() -> None:
    host = os.getenv("NEBULA_ONE_HOST", "127.0.0.1")
    port = int(os.getenv("NEBULA_ONE_PORT", "8088"))
    # the root logger sits at WARNING and uvicorn only configures its own loggers, so without
    # this the lifespan's seed autoload summary — the only record of what a boot installed —
    # is dropped before it reaches the log
    application_logger = logging.getLogger("nebula_one")
    application_logger.addHandler(logging.StreamHandler())
    application_logger.setLevel(logging.INFO)
    uvicorn.run("nebula_one.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
