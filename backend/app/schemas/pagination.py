"""Common pagination response model for collection endpoints."""

from pydantic import BaseModel, ConfigDict, Field


class PageResponse[ItemT](BaseModel):
    """Stable page metadata shared by account and transaction lists."""

    model_config = ConfigDict(extra="forbid")

    items: list[ItemT]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)


def page_response[ItemT](
    *, items: list[ItemT], total: int, page: int, page_size: int
) -> PageResponse[ItemT]:
    """Build a page with a zero-page result for empty collections."""

    return PageResponse[ItemT](
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size,
    )
