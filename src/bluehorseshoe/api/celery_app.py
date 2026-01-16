import os
from celery import Celery

# Get configuration from environment variables
BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/0")

celery_app = Celery(
    "bluehorseshoe",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["bluehorseshoe.api.tasks"]
)

# Optional: Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # 1 hour hard limit for tasks (prediction can be long)
    task_time_limit=3600, 
)
