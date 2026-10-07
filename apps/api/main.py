from fastapi import FastAPI

from apps.api.routes import health

app = FastAPI(title="PatchPulse", version="0.1.0")
app.include_router(health.router)
