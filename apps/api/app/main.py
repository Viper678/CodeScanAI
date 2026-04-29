from fastapi import FastAPI

from app.routers.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="CodeScan API")
    app.include_router(health_router)
    return app


app = create_app()
