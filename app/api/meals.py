from fastapi import APIRouter

from app.schemas.meals import AnalyzeMealRequest, AnalyzeMealResponse
from app.services.meal_analysis import get_meal_analysis_service

router = APIRouter(prefix="/api/v1/meals", tags=["meals"])


@router.post("/analyze", response_model=AnalyzeMealResponse)
async def analyze_meal(
    request: AnalyzeMealRequest,
) -> AnalyzeMealResponse:
    # Initialize after body validation so malformed requests still return 422
    # even when the service has not yet been configured.
    service = get_meal_analysis_service()
    return await service.analyze(str(request.imageUrl))
