"""Celery wiring for pipeline stages. Stage tasks are added in later steps."""

from celery import Celery

from apps.api.config import get_settings

settings = get_settings()

celery_app = Celery("patchpulse", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1)


@celery_app.task(name="pipeline.ping")
def ping() -> str:
    return "pong"
