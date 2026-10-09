from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from html import escape
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, Field, field_validator

from .infrai_email import InfraiReply


class ReceiptState(StrEnum):
    SENT = "sent"
    OPENED = "opened"
    BOUNCED = "bounced"


class FulfillmentState(StrEnum):
    CHECKOUT = "checkout"
    PACKED = "packed"
    SHIPPED = "shipped"


class CheckoutRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=80)
    customer_email: str = Field(min_length=3, max_length=254)
    customer_name: str = Field(min_length=1, max_length=120)
    amount_cents: int = Field(gt=0)

    @field_validator("customer_email")
    @classmethod
    def validate_customer_email(cls, value: str) -> str:
        local, separator, domain = value.rpartition("@")
        if not separator or not local or "." not in domain:
            raise ValueError("customer_email must be an email address")
        return value


class FulfillmentRequest(BaseModel):
    state: FulfillmentState


class OrderView(BaseModel):
    order_id: str
    customer_email: str
    amount_cents: int
    fulfillment: FulfillmentState
    receipt: ReceiptState
    message_id: str


@dataclass
class OrderRecord:
    order_id: str
    customer_email: str
    customer_name: str
    amount_cents: int
    fulfillment: FulfillmentState
    receipt: ReceiptState
    message_id: str

    def view(self) -> OrderView:
        return OrderView(
            order_id=self.order_id,
            customer_email=self.customer_email,
            amount_cents=self.amount_cents,
            fulfillment=self.fulfillment,
            receipt=self.receipt,
            message_id=self.message_id,
        )


BOUNCE_EVENTS = {"bounce", "bounced", "delivery_bounced"}
OPEN_EVENTS = {"open", "opened", "email_opened"}


def decide_receipt_state(events: Iterable[Mapping[str, Any]]) -> ReceiptState:
    kinds = {
        str(event.get("type") or event.get("event") or "").lower()
        for event in events
    }
    if kinds & BOUNCE_EVENTS:
        return ReceiptState.BOUNCED
    if kinds & OPEN_EVENTS:
        return ReceiptState.OPENED
    return ReceiptState.SENT


class OrderBook:
    def __init__(self, email: Any) -> None:
        self.email = email
        self.orders: dict[str, OrderRecord] = {}

    def checkout(self, request: CheckoutRequest) -> OrderView:
        amount = f"${request.amount_cents / 100:.2f}"
        reply = self.email.send(
            {
                "to": str(request.customer_email),
                "subject": f"Receipt for order {request.order_id}",
                "html": (
                    f"<h1>Thanks, {escape(request.customer_name)}</h1>"
                    f"<p>We received order <strong>{escape(request.order_id)}</strong> "
                    f"for {amount}.</p>"
                ),
            },
            idempotency_key=f"receipt:{request.order_id}",
        )
        message_id = str(reply.data["message_id"])
        record = OrderRecord(
            order_id=request.order_id,
            customer_email=str(request.customer_email),
            customer_name=request.customer_name,
            amount_cents=request.amount_cents,
            fulfillment=FulfillmentState.CHECKOUT,
            receipt=ReceiptState.SENT,
            message_id=message_id,
        )
        self.orders[record.order_id] = record
        return record.view()

    def set_fulfillment(self, order_id: str, state: FulfillmentState) -> OrderView:
        record = self.orders[order_id]
        record.fulfillment = state
        return record.view()

    def refresh_receipt(self, order_id: str) -> OrderView:
        record = self.orders[order_id]
        self.email.get(record.message_id)
        reply = self.email.event.list(message_id=record.message_id)
        data = reply.data
        events = data if isinstance(data, list) else data.get("items", [])
        record.receipt = decide_receipt_state(events)
        return record.view()
