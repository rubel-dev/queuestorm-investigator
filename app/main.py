from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="QueueStorm Investigator",
        version="0.1.0",
        description="Offline rule-based support ticket investigator for digital finance complaints.",
    )

    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        error_types = {str(error.get("type", "")) for error in exc.errors()}
        status_code = 400 if error_types.intersection({"json_invalid", "missing"}) else 422

        return JSONResponse(
            status_code=status_code,
            content={
                "error": "invalid_request",
                "message": "Request body does not match the required schema.",
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if isinstance(exc.detail, dict):
            content = exc.detail
        else:
            content = {
                "error": "http_error",
                "message": "The request could not be processed.",
            }

        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "The service encountered an internal error.",
            },
        )

    return app


app = create_app()
