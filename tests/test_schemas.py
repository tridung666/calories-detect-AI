import pytest
from pydantic import ValidationError

from app.schemas.meals import AnalyzeMealRequest, AnalyzeMealResponse, NutritionItem


def test_valid_prediction(nutrition_item):
    result = AnalyzeMealResponse.model_validate({"items": [nutrition_item]})
    assert result.model_dump() == {"items": [nutrition_item]}


@pytest.mark.parametrize("field,value", [
    ("name", ""), ("name", "  \t"), ("name", None),
    ("estimatedGrams", 0), ("estimatedGrams", -1),
    ("calories", -1), ("protein", -1), ("carbohydrate", -1), ("fat", -1),
    ("confidence", -0.1), ("confidence", 1.1),
    ("calories", float("nan")), ("fat", float("inf")),
    ("estimatedGrams", float("inf")), ("confidence", float("nan")),
    ("calories", "248"), ("protein", True), ("name", 123),
    ("name", "x" * 256), ("estimatedGrams", 100000000),
    ("estimatedGrams", 0.004), ("calories", 2147483648),
])
def test_invalid_item(nutrition_item, field, value):
    with pytest.raises(ValidationError):
        NutritionItem.model_validate({**nutrition_item, field: value})


@pytest.mark.parametrize("confidence", [0, 1])
def test_confidence_boundaries(nutrition_item, confidence):
    assert NutritionItem.model_validate({**nutrition_item, "confidence": confidence}).confidence == confidence


def test_name_trimmed(nutrition_item):
    assert NutritionItem.model_validate({**nutrition_item, "name": " Rice "}).name == "Rice"


def test_prediction_rounds_to_confirmed_storage_precision(nutrition_item):
    item = NutritionItem.model_validate({**nutrition_item, "estimatedGrams": 150.125,
                                         "protein": 46.555, "confidence": 0.91234})
    assert item.estimatedGrams == 150.13
    assert item.protein == 46.56
    assert item.confidence == 0.91234


def test_no_extra_or_missing_fields(nutrition_item):
    with pytest.raises(ValidationError):
        NutritionItem.model_validate({**nutrition_item, "explanation": "extra"})
    del nutrition_item["fat"]
    with pytest.raises(ValidationError):
        NutritionItem.model_validate(nutrition_item)


@pytest.mark.parametrize("payload", [
    {}, {"imageUrl": None},
    {"imageUrl": "not-a-url"},
    {"imageUrl": "ftp://example.com/image.jpg"},
    {"imageUrl": "https://example.com/bad image.jpg"},
    {"imageUrl": "https://user:pass@example.com/image.jpg"},
    {"mealId": 123, "imageUrl": "https://example.com/image.jpg"},
])
def test_invalid_request(payload):
    with pytest.raises(ValidationError):
        AnalyzeMealRequest.model_validate(payload)


def test_request_accepts_signed_url():
    url = "https://res.cloudinary.com/demo/image/upload/meal.jpg?signature=abc&expires=123"
    assert str(AnalyzeMealRequest(imageUrl=url).imageUrl) == url
