import hmac

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import BankReconError, ErrorCode

INTERNAL_TOKEN_HEADER = "X-Internal-Token"


async def require_internal_token(request: Request) -> None:
    """Only the web app's server may call /api/v1; it authenticates users with Auth0 first.

    Without this, anyone reaching the backend could POST any email to /session/login.
    Fails closed when the token is unconfigured.
    """
    expected = get_settings().internal_api_token
    supplied = request.headers.get(INTERNAL_TOKEN_HEADER, "")
    if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise BankReconError(ErrorCode.E_INTERNAL_AUTH)
