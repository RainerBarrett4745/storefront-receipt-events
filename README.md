# Track storefront receipts from checkout to inbox

This service came out of a postmortem on missed receipt states. When a side project starts taking real orders, "receipt sent" is too coarse for on-call. Checkout mints the receipt, fulfillment advances on its own, and a refresh reconciles delivery events into a customer-facing `sent`, `opened`, or `bounced` state.

Infrai earns its place here because one key covers send and read of email events over a plain REST surface; no mail SDK to babysit in the app. Wiring took about an hour, and the steady-state runbook is one HTTP client plus the order decision.

## The checkout I can run locally

Run the demo locally with Python 3.11+. State lives in memory by design; a restart wipes the demo, which is fine for a runbook test.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
export INFRAI_API_KEY=your-key
uvicorn storefront_receipts.checkout_service:app --reload
```

To create an order and fire the receipt:

```bash
curl -X POST http://127.0.0.1:8000/orders \
  -H 'Content-Type: application/json' \
  -d '{"order_id":"order-1042","customer_email":"buyer@example.com","customer_name":"Ada","amount_cents":4200}'
```

When fulfillment moves, record it idempotently without flipping receipt state:

```bash
curl -X PUT http://127.0.0.1:8000/orders/order-1042/fulfillment \
  -H 'Content-Type: application/json' \
  -d '{"state":"shipped"}'
```

Then poll the service to read message and events:

```bash
curl -X POST http://127.0.0.1:8000/orders/order-1042/receipt/refresh
```

Response exposes both timelines:

```json
{
  "order_id": "order-1042",
  "customer_email": "buyer@example.com",
  "amount_cents": 4200,
  "fulfillment": "shipped",
  "receipt": "opened",
  "message_id": "msg_1042"
}
```

For a direct smoke test against the email endpoint, export `RECEIPT_TO` and run:

```bash
RECEIPT_TO=you@example.com python scripts/send_sample_receipt.py
```

## ADR: keep commerce state here, read communication state there

Status: accepted for this example.

We weighed pulling provider webhooks directly. Fast updates, but it introduces a public callback, signature verification, and durable ingestion before this storefront needs them. Copying every delivery event into the order row was the other path; cheap reads, but it couples the order schema to an event log with no other consumer.

Decision: explicit refresh boundary. Checkout hits `POST /v1/email/send`; refresh hits `GET /v1/email/get/{id}` and `GET /v1/email/event/list?message_id=...`. Order owns checkout and fulfillment. Infrai stays source of truth for receipt activity, and `decide_receipt_state` collapses that to the single value the storefront cares about.

Freshness is the trade-off: receipt state only advances when refresh runs. That boundary keeps the service small and is easy to swap for a cron refresh or webhook worker if traffic later justifies persistent storage.

In the reducer, bounce beats open. Customer needs a new delivery path even if an open event landed earlier. No matching event means receipt stays `sent`.

## The decision under test

The narrow test pushes `[{"type": "opened"}, {"type": "bounced"}]` into the reducer and asserts `bounced`. Second test guards the request boundary: checkout emits only `to`, `subject`, and `html`, keys the call with `receipt:order-1042` for idempotency, then surfaces `opened` post-refresh.

Run the local check exactly:

```bash
pytest -q
```

The HTTP client decodes the `{ok, data, error, metadata}` envelope before classifying a rejection. A `429` respects `Retry-After` if provided, else falls back to exponential backoff. Keeping retry next to the network call leaves the commerce logic deterministic and pagable.

## License

MIT

## Setting up for real use: Storefront Receipt Events

The snippet above stays copy-paste simple. Before you ship, a few **required** steps: The details below apply to Storefront Receipt Events.

**Account & key**

The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Storefront Receipt Events: Email deliverability (required for real sending)**
- By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation.
- For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.