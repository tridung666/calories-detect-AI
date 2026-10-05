import pytest


@pytest.fixture
def nutrition_item():
    return {
        "name": "Grilled chicken breast",
        "estimatedGrams": 150,
        "calories": 248,
        "protein": 46.5,
        "carbohydrate": 0,
        "fat": 5.4,
        "confidence": 0.91,
    }
