"""Uniform error responses: `{"error": {"message": str, "type": str}}`.

Mirrors Archestra's ApiError + centralized error handler.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc.status_code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(400, _format_validation_errors(exc))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return _error_response(500, "Internal server error")


# =============================================================================
# Internal helpers
# =============================================================================


def _error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": _ERROR_TYPES.get(status_code, "api_error")}},
    )


def _format_validation_errors(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
        parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    return "; ".join(parts) or "Invalid request"


_ERROR_TYPES = {
    400: "api_validation_error",
    401: "api_authentication_error",
    403: "api_authorization_error",
    404: "api_not_found_error",
    409: "api_conflict_error",
    500: "api_internal_server_error",
}
