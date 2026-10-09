import os

from storefront_receipts.infrai_email import InfraiClient
from storefront_receipts.order_updates import CheckoutRequest, OrderBook


recipient = os.environ.get("RECEIPT_TO")
if not recipient:
    raise RuntimeError("RECEIPT_TO is required")

book = OrderBook(InfraiClient.from_environment().email)
result = book.checkout(
    CheckoutRequest(
        order_id="demo-1042",
        customer_email=recipient,
        customer_name="Ada",
        amount_cents=4200,
    )
)
print(result.model_dump_json(indent=2))
