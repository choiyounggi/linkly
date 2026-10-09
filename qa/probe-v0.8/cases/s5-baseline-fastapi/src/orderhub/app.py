from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from orderhub.errors import BusinessRule, Forbidden, IllegalTransition, InjectedFailure, NotFound
from orderhub.orders.router import router as orders_router
from orderhub.payments.router import router as payments_router

app = FastAPI(title="OrderHub", openapi_version="3.1.0")
app.include_router(orders_router)
app.include_router(payments_router)


def _problem(status: int, title: str, code: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://orderhub.example/errors/{code}",
            "title": title,
            "status": status,
            "detail": detail,
            "code": code,
        },
    )


@app.exception_handler(BusinessRule)
def business_rule_handler(request: Request, exc: BusinessRule):
    return _problem(422, "Business rule violation", exc.code, exc.detail)


@app.exception_handler(NotFound)
def not_found_handler(request: Request, exc: NotFound):
    return _problem(404, "Not found", exc.code, exc.detail)


@app.exception_handler(IllegalTransition)
def illegal_transition_handler(request: Request, exc: IllegalTransition):
    return _problem(409, "Illegal transition", exc.code, exc.detail)


@app.exception_handler(Forbidden)
def forbidden_handler(request: Request, exc: Forbidden):
    return _problem(403, "Forbidden", exc.code, exc.detail)


@app.exception_handler(InjectedFailure)
def injected_failure_handler(request: Request, exc: InjectedFailure):
    return _problem(500, "Injected failure", exc.code, exc.detail)
