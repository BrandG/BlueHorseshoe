import logging
import time
from fastapi import FastAPI
from contextlib import asynccontextmanager

from bluehorseshoe.api.routes import router
from bluehorseshoe.core.container import create_app_container

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("bluehorseshoe.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    Initializes dependency injection container and manages resource lifecycle.
    """
    logger.info("Starting BlueHorseshoe API...")

    # Create and store container in app state
    app.state.container = create_app_container()

    # Test MongoDB connection
    try:
        app.state.container.get_mongo_client().server_info()
        logger.info("Connected to MongoDB successfully")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")

    yield

    # Cleanup resources
    logger.info("Shutting down BlueHorseshoe API...")
    app.state.container.close()

app = FastAPI(
    title="BlueHorseshoe API",
    description="Quantitative Trading Analysis API",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(router, prefix="/api/v1")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bluehorseshoe.api.main:app", host="0.0.0.0", port=8000, reload=True)
