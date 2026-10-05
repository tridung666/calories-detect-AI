from typing import Annotated
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class AnalyzeMealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imageUrl: HttpUrl

    @field_validator("imageUrl", mode="before")
    @classmethod
    def reject_url_whitespace(cls, value):
        if isinstance(value, str) and any(character.isspace() for character in value):
            raise ValueError("imageUrl must not contain whitespace")
        return value

    @field_validator("imageUrl")
    @classmethod
    def reject_url_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username is not None or value.password is not None:
            raise ValueError("imageUrl must not contain credentials")
        return value


NonNegativeNumber = Annotated[float, Field(ge=0, le=2147483647, strict=True, allow_inf_nan=False)]


class NutritionItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=255)
    estimatedGrams: float = Field(gt=0, le=99999999.99, allow_inf_nan=False)
    calories: NonNegativeNumber
    protein: NonNegativeNumber
    carbohydrate: NonNegativeNumber
    fat: NonNegativeNumber
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator("estimatedGrams", "calories", "protein", "carbohydrate", "fat")
    @classmethod
    def round_portion_values(cls, value: float, info) -> float:
        rounded = float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        if info.field_name == "estimatedGrams" and rounded <= 0:
            raise ValueError("estimatedGrams must remain positive after rounding to two decimals")
        return rounded

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class AnalyzeMealResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: list[NutritionItem]
