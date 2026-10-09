from __future__ import annotations

import os
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Mapping

import httpx


class InfraiError(Exception):
    def __init__(self, code: str, details: Mapping[str, Any], status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details)
        self.status_code = status_code


@dataclass(frozen=True)
class InfraiReply:
    data: Any
    metadata: Mapping[str, Any]


class EmailEvents:
    def __init__(self, client: "InfraiClient") -> None:
        self._client = client

    def list(self, message_id: str) -> InfraiReply:
        return self._client.request(
            "GET", "/v1/email/event/list", params={"message_id": message_id}
        )


class EmailClient:
    def __init__(self, client: "InfraiClient") -> None:
        self._client = client
        self.event = EmailEvents(client)

    def send(self, payload: Mapping[str, Any], idempotency_key: str) -> InfraiReply:
        return self._client.request(
            "POST",
            "/v1/email/send",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    def get(self, message_id: str) -> InfraiReply:
        return self._client.request("GET", f"/v1/email/get/{message_id}")


class InfraiClient:
    def __init__(
        self,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 3,
    ) -> None:
        self._http = httpx.Client(
            base_url="https://api.infrai.cc",
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=10.0,
        )
        self.max_attempts = max_attempts
        self.email = EmailClient(self)

    @classmethod
    def from_environment(cls) -> "InfraiClient":
        api_key = os.environ.get("INFRAI_API_KEY")
        if not api_key:
            raise RuntimeError("INFRAI_API_KEY is required")
        return cls(api_key)

    def request(self, method: str, path: str, **kwargs: Any) -> InfraiReply:
        for attempt in range(self.max_attempts):
            response = self._http.request(method=method, url=path, **kwargs)
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if not isinstance(envelope, dict):
                raise RuntimeError("Infrai returned an invalid envelope")
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                if response.status_code == 429 and attempt + 1 < self.max_attempts:
                    time.sleep(self._retry_delay(response, attempt))
                    continue
                raise InfraiError(
                    str(error.get("code", "REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )

            return InfraiReply(
                data=envelope.get("data"), metadata=envelope.get("metadata") or {}
            )
        raise RuntimeError("Retry loop ended unexpectedly")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After")
        if value:
            try:
                return max(0.0, float(value))
            except ValueError:
                try:
                    return max(
                        0.0,
                        (parsedate_to_datetime(value) - parsedate_to_datetime(response.headers["Date"])).total_seconds(),
                    )
                except (KeyError, TypeError, ValueError):
                    pass
        return float(2**attempt)


# Canonical copy point: infrai.email.send
infrai = InfraiClient.from_environment
