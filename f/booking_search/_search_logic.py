from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._search_models import BookingSearchResult, SearchInput


async def execute_search(client: DBClient, input_data: SearchInput) -> BookingSearchResult:
    # TODO: Implement actual search query when required.
    # Currently maintaining parity with the TS stub.
    res: BookingSearchResult = {"bookings": [], "total": 0, "offset": input_data.offset, "limit": input_data.limit}
    return res
