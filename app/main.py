from fastapi import FastAPI
from app.container import build_container
from app.api.v1.webhook import create_webhook_router
from app.core.lifespan import create_lifespan
from app.core.config import settings

def create_app() -> FastAPI:
    container = build_container(settings)

    app = FastAPI(
        title="Titanium Booking Engine",
        version="0.1.0",
        lifespan=create_lifespan(container),
    )
    
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    webhook_router = create_webhook_router(container)
    app.include_router(webhook_router, prefix="/api/v1", tags=["telegram"])
    
    from app.api.v1 import provider
    app.include_router(provider.router, prefix="/api/v1", tags=["provider"])

    # Set container in app state so middleware/endpoints can access it if needed
    app.state.container = container

    @app.get("/health")
    async def health_check():
        return {"status": "healthy"}

    return app

app = create_app()
