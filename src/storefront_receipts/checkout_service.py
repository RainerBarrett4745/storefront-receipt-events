from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .infrai_email import InfraiClient, InfraiError
from .order_updates import CheckoutRequest, FulfillmentRequest, OrderBook, OrderView


def create_app(client: InfraiClient | None = None) -> FastAPI:
    app = FastAPI(title="Storefront receipt events")
    order_book = OrderBook((client or InfraiClient.from_environment()).email)

    @app.exception_handler(InfraiError)
    async def handle_infrai_error(_request: object, exc: InfraiError) -> JSONResponse:
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        return JSONResponse(status_code=status, content={"detail": {"code": exc.code}})

    @app.post("/orders", response_model=OrderView, status_code=201)
    def checkout(request: CheckoutRequest) -> OrderView:
        if request.order_id in order_book.orders:
            return order_book.orders[request.order_id].view()
        return order_book.checkout(request)

    @app.put("/orders/{order_id}/fulfillment", response_model=OrderView)
    def fulfill(order_id: str, request: FulfillmentRequest) -> OrderView:
        try:
            return order_book.set_fulfillment(order_id, request.state)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="order not found") from exc

    @app.post("/orders/{order_id}/receipt/refresh", response_model=OrderView)
    def refresh_receipt(order_id: str) -> OrderView:
        try:
            return order_book.refresh_receipt(order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="order not found") from exc

    return app


app = create_app()
