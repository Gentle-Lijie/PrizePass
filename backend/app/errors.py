from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and {"code", "message"}.issubset(exc.detail):
            error = exc.detail
        else:
            error = {"code": "http_error", "message": str(exc.detail), "details": {}}
        return JSONResponse(status_code=exc.status_code, content={"error": error})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for issue in exc.errors():
            clean_issue = {key: value for key, value in issue.items() if key != "ctx"}
            errors.append(clean_issue)
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "请求数据校验失败",
                    "details": {"errors": errors},
                }
            },
        )
