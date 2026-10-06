import pytest
import httpx
from gianna.adapters.tickets_http import TicketError
from gianna.adapters.playwright_browser import BrowserContractError
from gianna.runtime.errors import ErrorCode, MESSAGES, classify


@pytest.mark.parametrize(
    "error,code",
    [
        (TicketError("auth_required", 401), ErrorCode.AUTH),
        (TicketError("forbidden", 403), ErrorCode.PERMISSION),
        (TicketError("version_conflict", 409), ErrorCode.VERSION),
        (TicketError("idempotency_conflict", 409), ErrorCode.IDEMPOTENCY),
        (TicketError("validation_error", 422), ErrorCode.VALIDATION),
        (TicketError("rate_limited", 429), ErrorCode.RATE),
        (BrowserContractError("browser_closed"), ErrorCode.UI),
        (httpx.ConnectError("connection unavailable"), ErrorCode.API),
        (TimeoutError(), ErrorCode.DEADLINE),
        (RuntimeError("outcome_unknown"), ErrorCode.UNKNOWN),
    ],
)
def test_failures_have_distinct_recoverable_codes(error, code):
    assert classify(error) == code
    assert MESSAGES[code]
