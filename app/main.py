from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.meals import router
from app.core.errors import MealAnalysisError
from app.core.config import get_settings

app = FastAPI(title="Meal Image Analysis API")
app.include_router(router)


@app.exception_handler(MealAnalysisError)
async def meal_analysis_error_handler(request: Request, exc: MealAnalysisError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "detail": exc.detail})


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
def ready() -> JSONResponse:
    # Configuration readiness only: no paid provider calls in health checks.
    settings = get_settings()
    configured = bool(settings.openai_api_key.get_secret_value().strip() and settings.openai_model.strip())
    return JSONResponse(status_code=200 if configured else 503,
                        content={"status": "ready" if configured else "not_configured"})
