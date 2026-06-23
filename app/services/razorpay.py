"""Razorpay client + signature helpers.

Phase 1 ships a FakeRazorpayClient so the enrollment flow is testable without
network access. With a real key configured (rzp_test_* or rzp_live_*) the
LiveRazorpayClient hits the real Razorpay Orders API — test keys ARE the real
test flow, so the switch is "Fake only when no key is set" (mirrors email.py).
"""

import hashlib
import hmac
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.config import Settings, get_settings
from app.models import Class, Cohort


@dataclass(frozen=True)
class CreatedOrder:
    order_id: str
    amount: int  # paise
    currency: str


class RazorpayClient(ABC):
    @abstractmethod
    async def create_order(
        self, *, amount: int, currency: str, receipt: str, notes: dict[str, str]
    ) -> CreatedOrder: ...


class FakeRazorpayClient(RazorpayClient):
    async def create_order(
        self, *, amount: int, currency: str, receipt: str, notes: dict[str, str]
    ) -> CreatedOrder:
        # Deterministic per receipt so re-ordering the same cohort/user is stable.
        order_id = "order_FAKE" + hashlib.sha1(receipt.encode()).hexdigest()[:14]
        return CreatedOrder(order_id=order_id, amount=amount, currency=currency)


class LiveRazorpayClient(RazorpayClient):
    """Real Razorpay Orders API. Auth is HTTP basic (key_id:key_secret)."""

    def __init__(self, settings: Settings):
        self._settings = settings

    async def create_order(
        self, *, amount: int, currency: str, receipt: str, notes: dict[str, str]
    ) -> CreatedOrder:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                "https://api.razorpay.com/v1/orders",
                auth=(self._settings.razorpay_key_id, self._settings.razorpay_key_secret),
                json={
                    "amount": amount,
                    "currency": currency,
                    "receipt": receipt,
                    "notes": notes,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return CreatedOrder(
            order_id=data["id"], amount=int(data["amount"]), currency=data["currency"]
        )


def get_razorpay_client() -> RazorpayClient:
    settings = get_settings()
    if settings.razorpay_key_id:
        return LiveRazorpayClient(settings)
    return FakeRazorpayClient()


# --- Signature helpers (used by endpoints AND tests) ---


def _sign(message: str, secret: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_payment_signature(
    *, order_id: str, payment_id: str, signature: str, secret: str
) -> bool:
    """Razorpay Checkout handler signature: HMAC_SHA256(order_id|payment_id, key_secret)."""
    expected = _sign(f"{order_id}|{payment_id}", secret)
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(*, raw_body: bytes, signature: str, secret: str) -> bool:
    """Webhook signature: HMAC_SHA256 over the raw request body with the webhook secret."""
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# --- Pricing ---


def effective_price_paise(cohort: Cohort, *, now: datetime | None = None) -> int | None:
    """Charged price in paise. Early-bird price wins while the deadline hasn't passed.

    Returns None when the cohort has no price set (not purchasable).
    """
    now = now or datetime.now(UTC)
    rupees: Decimal | None
    deadline = cohort.early_bird_deadline
    if deadline is not None and deadline.tzinfo is None:
        # SQLite (tests) can drop tzinfo on round-trip; assume UTC.
        deadline = deadline.replace(tzinfo=UTC)
    if cohort.early_bird_price is not None and deadline is not None and now < deadline:
        rupees = cohort.early_bird_price
    else:
        rupees = cohort.price
    if rupees is None:
        return None
    return int((rupees * 100).to_integral_value())


def class_price_paise(klass: Class) -> int | None:
    """Single-class price in paise. None when the class has no price (not purchasable)."""
    if klass.price_single is None:
        return None
    return int((klass.price_single * 100).to_integral_value())
