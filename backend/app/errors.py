import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("foodsight")
UNEXPECTED = "Sorry, something went wrong on our side. Please try again."


# Any error a route did not handle: logged with its trace, and answered as JSON the app can show.
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": UNEXPECTED})


def handle_unexpected_errors(app: FastAPI) -> None:
    app.add_exception_handler(Exception, unexpected_error)
