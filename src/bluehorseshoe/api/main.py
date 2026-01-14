import logging
import time
from fastapi import FastAPI
from contextlib import asynccontextmanager

from bluehorseshoe.api.routes import router
from bluehorseshoe.core.globals import get_mongo_client

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
    """
    logger.info("Starting BlueHorseshoe API...")
    
    # Initialize DB connection on startup
    client = get_mongo_client()
    if client is None:
        logger.error("Failed to connect to MongoDB on startup.")
    else:
        logger.info("Connected to MongoDB.")
    
    yield
    
    logger.info("Shutting down BlueHorseshoe API...")

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
