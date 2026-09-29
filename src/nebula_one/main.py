from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .api import router
from .config import Settings
from .container import build_container
from .errors import DomainError
from .runtime_api import router as runtime_router
from .modeling_api import router as modeling_router
from .web_assets import SpaStaticFiles, usable_web_root

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    engine_transport=None,
) -> FastAPI:
    active_settings = settings or Settings.from_env()
    container = build_container(active_settings, engine_transport=engine_transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            container.database.prepare_schema()
            summary = container.seed_autoload.run()
            logger.info(
                "seed autoload finished with result=%s over %d step(s)",
                summary["result"],
                len(summary["steps"]),
            )
            # the per-step record is what tells an acceptance run whether a boot wrote a row or
            # proved the declared one was already there; the counts above cannot tell those apart
            logger.info("seed autoload steps %s", json.dumps(summary["steps"], ensure_ascii=False))
            yield
        finally:
            container.client.close()
            container.database.dispose()

    application = FastAPI(
        title="Nebula One API",
        version=__version__,
        description="Application-layer sustainability analysis over exact Nebula LCA model versions.",
        lifespan=lifespan,
    )
    application.state.container = container

    @application.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    application.include_router(router)
    application.include_router(runtime_router)
    application.include_router(modeling_router)
    web_root = usable_web_root(active_settings.web_root)
    if web_root is not None:
        application.mount(
            "/",
            SpaStaticFiles(directory=str(web_root), html=True),
            name="web",
        )
    return application


app = create_app()
