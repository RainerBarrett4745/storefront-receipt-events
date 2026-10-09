from typing import Any

from storefront_receipts.infrai_email import InfraiReply
from storefront_receipts.order_updates import (
    CheckoutRequest,
    OrderBook,
    ReceiptState,
    decide_receipt_state,
)


class FakeEvents:
    def __init__(self, events: list[dict[str, str]]) -> None:
        self.events = events

    def list(self, message_id: str) -> InfraiReply:
        assert message_id == "msg_1042"
        return InfraiReply(data={"items": self.events}, metadata={})


class FakeEmail:
    def __init__(self, events: list[dict[str, str]]) -> None:
        self.event = FakeEvents(events)
        self.sent: dict[str, Any] = {}

    def send(self, payload: dict[str, Any], idempotency_key: str) -> InfraiReply:
        self.sent = {"payload": payload, "idempotency_key": idempotency_key}
        return InfraiReply(data={"message_id": "msg_1042"}, metadata={})

    def get(self, message_id: str) -> InfraiReply:
        assert message_id == "msg_1042"
        return InfraiReply(data={"message_id": message_id}, metadata={})


def test_bounce_wins_when_a_receipt_was_opened_first() -> None:
    events = [{"type": "opened"}, {"type": "bounced"}]
    assert decide_receipt_state(events) is ReceiptState.BOUNCED


def test_checkout_and_refresh_expose_customer_update() -> None:
    email = FakeEmail([{"type": "opened"}])
    book = OrderBook(email)

    created = book.checkout(
        CheckoutRequest(
            order_id="order-1042",
            customer_email="buyer@example.com",
            customer_name="Ada & Co",
            amount_cents=4200,
        )
    )
    refreshed = book.refresh_receipt(created.order_id)

    assert email.sent["idempotency_key"] == "receipt:order-1042"
    assert email.sent["payload"] == {
        "to": "buyer@example.com",
        "subject": "Receipt for order order-1042",
        "html": (
            "<h1>Thanks, Ada &amp; Co</h1>"
            "<p>We received order <strong>order-1042</strong> for $42.00.</p>"
        ),
    }
    assert refreshed.receipt is ReceiptState.OPENED
