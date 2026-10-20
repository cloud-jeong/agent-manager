from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """API models use camelCase on the wire and snake_case in Python."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class Pagination(CamelModel):
    total: int
    limit: int
    offset: int
    has_next: bool


class Paginated[T](CamelModel):
    data: list[T]
    pagination: Pagination


class SuccessResponse(CamelModel):
    success: bool = True
