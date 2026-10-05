"""Pidge, behind the delivery contracts.

Verified against their sandbox (`store.dev.pidge.in`) rather than written from
the documentation, because three things differ from what the Postman page
says. Each is recorded at the line it affects:

* the address field is `address_line_1`, not `line1`;
* the create response is keyed by OUR `source_order_id`, not by their id;
* `brand` is refused on a vendor account — "Brand is allowed only for
  aggregator(6)" — so it is sent only when a brand code is configured.

Their sixteen fulfillment statuses collapse into the seven of
`DeliveryState`; see `_STATES` for what each one is taken to mean and why the
return-to-origin family is FAILED rather than CANCELLED.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from app.config import get_settings
from app.services.delivery.base import (
    DeliveryAddress,
    DeliveryProviderError,
    DeliveryQuote,
    DeliveryRequest,
    DeliveryResult,
    DeliveryState,
)

logger = logging.getLogger(__name__)
settings = get_settings()

PROVIDER_NAME = "pidge"

#: Their fulfillment vocabulary, mapped onto ours.
#:
#: The RTO ("return to origin") family and UNDELIVERED are FAILED, not
#: CANCELLED. The food was cooked and dispatched; it is now back at the
#: restaurant or lost. Folding that into CANCELLED would erase the difference
#: between an order nobody started and an order somebody paid for, made, and
#: could not hand over — which is the only distinction that matters when
#: deciding who bears the cost.
_STATES = {
    "CREATED": DeliveryState.PENDING,
    "PENDING": DeliveryState.PENDING,
    "OUT_FOR_PICKUP": DeliveryState.ASSIGNED,
    "REACHED_PICKUP": DeliveryState.ASSIGNED,
    "PICKED_UP": DeliveryState.PICKED_UP,
    "IN_TRANSIT": DeliveryState.IN_TRANSIT,
    "OUT_FOR_DELIVERY": DeliveryState.IN_TRANSIT,
    "REACHED_DELIVERY": DeliveryState.IN_TRANSIT,
    "DELIVERED": DeliveryState.DELIVERED,
    "CANCELLED": DeliveryState.CANCELLED,
    "UNDELIVERED": DeliveryState.FAILED,
    "RTO_OUT_FOR_DELIVERY": DeliveryState.FAILED,
    "RTO_UNDELIVERED": DeliveryState.FAILED,
    "RTO_DELIVERED": DeliveryState.FAILED,
    "DISPOSED": DeliveryState.FAILED,
    "LOST": DeliveryState.FAILED,
    "DAMAGED": DeliveryState.FAILED,
}

#: The parent-level status, used only when no fulfillment status has appeared
#: yet — a freshly created order reads `status: "pending"` and nothing else.
_PARENT_STATES = {
    "pending": DeliveryState.PENDING,
    "fulfilled": DeliveryState.ASSIGNED,
    "completed": DeliveryState.DELIVERED,
    "cancelled": DeliveryState.CANCELLED,
}


def state_for(fulfillment_status: str | None, parent_status: str | None = None) -> DeliveryState:
    """What a Pidge status means here.

    Unknown strings become PENDING rather than raising: a courier adding a
    status to its own vocabulary must not take an order down with it, and
    PENDING is the state that keeps everything watching.
    """

    if fulfillment_status:
        mapped = _STATES.get(str(fulfillment_status).strip().upper())
        if mapped is not None:
            return mapped
    if parent_status:
        mapped = _PARENT_STATES.get(str(parent_status).strip().lower())
        if mapped is not None:
            return mapped
    if fulfillment_status or parent_status:
        logger.warning(
            "Unknown Pidge status fulfillment=%r parent=%r", fulfillment_status, parent_status
        )
    return DeliveryState.PENDING


def _address(address: DeliveryAddress) -> dict[str, Any]:
    """One address, in Pidge's shape.

    `address_line_1` — not `line1`, which is what the documentation implies
    and what a 400 corrects you on.
    """

    payload: dict[str, Any] = {
        "address_line_1": address.address_line_1,
        "city": address.city,
        "state": address.state,
        "pincode": address.pincode,
        "country": address.country,
    }
    if address.address_line_2:
        payload["address_line_2"] = address.address_line_2
    if address.latitude is not None and address.longitude is not None:
        payload["latitude"] = address.latitude
        payload["longitude"] = address.longitude
    if address.instructions:
        payload["instructions"] = address.instructions
    return payload


def pidge_mobile(value: str) -> str:
    """An Indian mobile as the ten digits Pidge's own examples use.

    Stored three ways here - a branch as "0" + ten digits, a customer as
    "+91" + ten, some with spaces - and a rider dialling "+919876543210" from
    a courier app built for ten is a call that may never connect. Anything
    that is not recognisably an Indian mobile is passed through untouched:
    refusing it here would lose the order, and Pidge says what it dislikes.
    """

    digits = "".join(character for character in value or "" if character.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    return value or ""


def _party(address: DeliveryAddress) -> dict[str, Any]:
    party: dict[str, Any] = {
        "address": _address(address),
        "name": address.name,
        "mobile": pidge_mobile(address.mobile),
    }
    if address.email:
        party["email"] = address.email
    return party


def pick_network(items: list[dict[str, Any]], *, preferred: str = "") -> dict[str, Any] | None:
    """Which of the networks Pidge offered should carry this order.

    Only one that answered without an error AND gave a price: a network with
    no price is one we would be booking blind. The preferred network wins if
    it qualifies; otherwise the cheapest that does.
    """

    usable = []
    for item in items:
        if item.get("error"):
            continue
        price = _money((item.get("quote") or {}).get("price"))
        if price is None:
            continue
        usable.append((price, item))
    if not usable:
        return None
    wanted = preferred.strip().lower()
    if wanted:
        for _, item in usable:
            if str(item.get("network_name") or item.get("service") or "").lower() == wanted:
                return item
    return min(usable, key=lambda pair: pair[0])[1]


class PidgeProvider:
    """Pidge's vendor API.

    The token is cached on the instance and refreshed on a 401, which is the
    only expiry signal their documentation offers: tokens are "generally
    persistent" but die on inactivity or a configuration change. Anything that
    is not a 401 is not an auth problem and is not retried by logging in
    again.
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        brand_code: str = "",
        brand_location_code: str = "",
        brand_name: str = "",
        preferred_network: str = "",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._brand_code = brand_code
        self._brand_location_code = brand_location_code
        self._brand_name = brand_name
        self._preferred_network = preferred_network
        self._timeout = timeout_seconds
        self._token: str | None = None
        # Two workers refreshing the same dead token would each log in; the
        # lock costs nothing and keeps it to one.
        self._lock = threading.Lock()

    def is_configured(self) -> bool:
        return bool(self._base_url and self._username and self._password)

    # --- auth -------------------------------------------------------------

    def _login(self) -> str:
        try:
            response = httpx.post(
                f"{self._base_url}/v1.0/store/channel/vendor/login",
                json={"username": self._username, "password": self._password},
                timeout=self._timeout,
            )
        except httpx.HTTPError as error:
            raise DeliveryProviderError(f"Could not reach Pidge to log in: {error}") from error
        if response.status_code >= 400:
            raise DeliveryProviderError(
                f"Pidge refused the login: {response.status_code}", retryable=False
            )
        token = ((response.json() or {}).get("data") or {}).get("token")
        if not token:
            # Their documentation is explicit that a revoked password returns
            # a body with no token rather than an error status.
            raise DeliveryProviderError(
                "Pidge returned no token — the password may have been revoked", retryable=False
            )
        return str(token)

    def _auth_header(self, *, force: bool = False) -> dict[str, str]:
        with self._lock:
            if force or not self._token:
                self._token = self._login()
            token = self._token
        # They return the token already carrying "Bearer ". Prefixing it again
        # produces "Bearer Bearer ..." and a 401 that looks like expiry.
        return {"Authorization": token if token.startswith("Bearer ") else f"Bearer {token}"}

    def _call(
        self, method: str, path: str, *, timeout: float | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """One authenticated request, retried once through a fresh login.

        `timeout` overrides the instance default for calls on a human's
        critical path. A dispatch runs on a worker and can afford to wait; a
        quote is blocking a checkout and cannot.
        """

        url = f"{self._base_url}{path}"
        for attempt in (1, 2):
            headers = self._auth_header(force=attempt == 2)
            try:
                response = httpx.request(
                    method, url, headers=headers, timeout=timeout or self._timeout, **kwargs
                )
            except httpx.HTTPError as error:
                raise DeliveryProviderError(f"Could not reach Pidge: {error}") from error
            if response.status_code == 401 and attempt == 1:
                logger.info("Pidge token expired; logging in again")
                continue
            if response.status_code >= 400:
                raise DeliveryProviderError(
                    f"Pidge refused {method} {path}: {response.status_code} "
                    f"{response.text[:300]}",
                    # A 4xx that is not 401 is our payload's fault and will
                    # fail identically on every retry.
                    retryable=response.status_code >= 500,
                )
            try:
                return response.json() or {}
            except ValueError as error:
                raise DeliveryProviderError(f"Pidge sent a non-JSON reply: {error}") from error
        raise DeliveryProviderError("Pidge kept refusing the token")

    # --- the contract -----------------------------------------------------

    def quote(
        self,
        *,
        pickup_lat: float,
        pickup_lng: float,
        drop_lat: float,
        drop_lng: float,
        timeout: float | None = None,
    ) -> DeliveryQuote:
        """What Pidge would charge for this trip, asked before it exists.

        Two calls, because they answer two different questions and only one of
        them can say no. `/serviceability` says whether any rider covers that
        pair of points; `/estimate` prices it. Asking for a price first and
        inferring "unserviceable" from a missing number would turn their
        outage into our silent free delivery.

        The two endpoints disagree about what a coordinate is called —
        serviceability wants `lat`/`lng`, estimate wants
        `latitude`/`longitude` — which is not in the documentation and is a
        400 if you assume they match.

        Nothing here invents a number. If Pidge prices nothing, the quote
        carries no cost and the caller decides what to do about it; a default
        fee baked in at this layer would be a made-up figure wearing a
        courier's name.
        """

        reachable = self._call(
            "POST",
            "/v1.0/store/channel/vendor/serviceability",
            timeout=timeout,
            json={
                "pickup": {"lat": pickup_lat, "lng": pickup_lng},
                "drop": {"lat": drop_lat, "lng": drop_lng},
            },
        )
        data = reachable.get("data")
        data = data if isinstance(data, dict) else {}
        # Absent rather than false is treated as serviceable: their own reply
        # for a covered pair is `{"serviceable": true}`, and a shape we do not
        # recognise should not silently refuse a customer who can be served.
        serviceable = data.get("serviceable")
        if serviceable is None:
            serviceable = reachable.get("serviceable", True)
        if not serviceable:
            return DeliveryQuote(serviceable=False, raw=reachable)

        priced = self._call(
            "POST",
            "/v1.0/store/channel/vendor/estimate",
            timeout=timeout,
            json={
                "pickup": {"latitude": pickup_lat, "longitude": pickup_lng},
                "drop": {"latitude": drop_lat, "longitude": drop_lng},
            },
        )
        estimate = priced.get("data")
        estimate = estimate if isinstance(estimate, dict) else priced

        return DeliveryQuote(
            serviceable=True,
            min_cost=_money(estimate.get("minCost")),
            max_cost=_money(estimate.get("maxCost")),
            # Pidge is an Indian courier and quotes rupees. They do not say so
            # in the payload, so it is asserted here rather than read.
            currency="INR",
            distance_metres=_float(estimate.get("pickupToDropDistance")),
            travel_seconds=_seconds(estimate.get("pickupToDropTime")),
            assign_seconds=_seconds(estimate.get("timeToAssign")),
            raw={"serviceability": reachable, "estimate": priced},
        )

    def create(self, request: DeliveryRequest) -> DeliveryResult:
        trip: dict[str, Any] = {
            "receiver_detail": _party(request.drop),
            "packages": [{
                "label": "Food order",
                "quantity": 1,
                "code": "PKG1",
                # Dimensions feed their volumetric weight, which feeds the
                # price. A placeholder here is a wrong invoice later.
                "weight": 1,
                "dimension": {"length": 25, "width": 25, "height": 15},
            }],
            "source_order_id": request.reference,
            "reference_id": request.reference,
            "cod_amount": float(request.cod_amount),
            "bill_amount": float(request.bill_amount),
            "order_category": "food",
            "products": [
                {
                    "name": item.name,
                    "sku": item.sku or item.name[:32],
                    "price": float(item.price),
                    "quantity": item.quantity,
                }
                for item in request.items
            ],
        }
        if request.ready_at is not None:
            trip["promised_prep_time"] = request.ready_at.isoformat()
        if request.deliver_by is not None:
            trip["promised_delivery_time"] = request.deliver_by.isoformat()
        if request.notes:
            # `name`/`value`, not `key`/`value` — another the sandbox corrects
            # you on and the documentation does not mention.
            trip["notes"] = [{"name": "instructions", "value": request.notes}]

        payload: dict[str, Any] = {
            "channel": "api",
            "sender_detail": _party(request.pickup),
            "poc_detail": {
                "name": request.pickup.name,
                "mobile": pidge_mobile(request.pickup.mobile),
                **({"email": request.pickup.email} if request.pickup.email else {}),
            },
            "trips": [trip],
        }
        # Only on an aggregator account. A vendor account answers "Brand is
        # allowed only for aggregator(6)" and rejects the whole order, so the
        # block is omitted entirely until a brand code is configured.
        if self._brand_code:
            payload["brand"] = {
                "code": self._brand_code,
                "location_code": self._brand_location_code,
                "name": self._brand_name,
            }

        body = self._call("POST", "/v1.0/store/channel/vendor/order", json=payload)
        # Keyed by OUR reference, not by their id: {"SMOKE-0001": "17906..."}.
        data = body.get("data") or {}
        provider_order_id = ""
        if isinstance(data, dict):
            provider_order_id = str(data.get(request.reference) or "")
            if not provider_order_id and len(data) == 1:
                # One trip was sent, so a single value is unambiguous even if
                # they key it differently than we asked.
                provider_order_id = str(next(iter(data.values())))
        if not provider_order_id:
            raise DeliveryProviderError(
                f"Pidge accepted the order but named no id: {body}", retryable=False
            )
        return DeliveryResult(
            provider_order_id=provider_order_id,
            state=DeliveryState.PENDING,
            reference=request.reference,
            raw=body,
        )

    def allocate(self, provider_order_id: str) -> str:
        """Ask a rider network to take an order Pidge is holding. Idempotent.

        Create Order leaves an order in Pending unless the account's token is
        set to auto-allocate, and nothing else asks anybody to carry it - the
        delivery used to sit on "Waiting for a rider" until it was cancelled.

        So: read the order once, and if Pidge already gave it to a network,
        stop - that is the auto-allocating account, and a second fulfil would
        be refused or, worse, book twice. Otherwise ask which networks can
        take it and fulfil with one (`pick_network`). The services call is
        CHARGED by Pidge, so this is called once at dispatch and again only
        when a person presses "Find a rider"; it never loops.

        Returns a short description of what was chosen ("pidge, Rs 70.8"), or
        "" when the order was already allocated. Raises `DeliveryProviderError`
        (retryable) when no network can take it right now.
        """

        status = self._call("GET", f"/v1.0/store/channel/vendor/order/{provider_order_id}")
        data = status.get("data") if isinstance(status.get("data"), dict) else status
        if isinstance(data, dict) and data.get("fulfillment"):
            return ""

        offered = self._call(
            "GET",
            "/v1.0/store/channel/vendor/order/fulfillment/services",
            params={"ids": provider_order_id},
        )
        body = offered.get("data")
        items = body.get("items") if isinstance(body, dict) else body
        items = [item for item in (items or []) if isinstance(item, dict)]
        chosen = pick_network(items, preferred=self._preferred_network)
        if chosen is None:
            reasons = sorted({
                str((item.get("error") or {}).get("message") or item.get("error"))
                for item in items
                if item.get("error")
            })
            detail = "; ".join(reasons) if reasons else "no network offered a price"
            raise DeliveryProviderError(
                f"No rider network can take this order right now ({detail})",
                retryable=True,
            )

        request: dict[str, Any] = {
            "ids": [provider_order_id],
            "service": chosen.get("service"),
            "pickup_now": bool(chosen.get("pickup_now", True)),
            "network_id": str(chosen.get("network_id")),
        }
        # Their own captive riders need no token; every partner network does.
        if chosen.get("token"):
            request["token"] = chosen["token"]
        self._call("POST", "/v1.0/store/channel/vendor/order/fulfill", json=request)
        price = (chosen.get("quote") or {}).get("price")
        return f"{chosen.get('network_name') or chosen.get('service')}, Rs {price}"

    def fetch(self, provider_order_id: str, *, simulate: str | None = None) -> DeliveryResult:
        """What Pidge says about one delivery now.

        `simulate` is the sandbox's `dummy_status`: the same response, as it
        would read at that stage of a trip ("fulfilled|picked up"). Pidge
        honours it on staging only, and the caller refuses it anywhere else.
        """

        params = {"dummy_status": simulate} if simulate else None
        body = self._call(
            "GET", f"/v1.0/store/channel/vendor/order/{provider_order_id}", params=params
        )
        return self._read(body.get("data") or body)

    def track(self, provider_order_id: str) -> tuple[float, float] | None:
        """Where the rider is right now, or None.

        Pidge rate-limits this to once per 30 seconds per order, across every
        caller, so it is asked from the one-minute sweep and nowhere else. It
        answers nulls before a rider moves and for a finished trip; both are
        None here rather than a point at 0,0 in the sea off West Africa.
        """

        try:
            body = self._call(
                "GET", f"/v1.0/store/channel/vendor/order/{provider_order_id}/fulfillment/tracking"
            )
        except DeliveryProviderError:
            return None
        location = ((body.get("data") or {}).get("location")) or {}
        latitude, longitude = _float(location.get("latitude")), _float(location.get("longitude"))
        if latitude is None or longitude is None:
            return None
        return latitude, longitude

    def cancel(self, provider_order_id: str) -> None:
        """Cancel the whole order at Pidge.

        The path has NO `/order/` segment — `/vendor/{id}/cancel`, where every
        other call here is `/vendor/order/...`. Writing it by analogy with
        `fetch` produces a 404 that reads like an unknown order.

        Pidge allows this only while the order is PENDING or FULFILLED, which
        is to say before a rider has the food. After that it answers 400
        `order.action.cancel.not-allowed`, and `_call` already raises that as
        non-retryable: it is a fact about the delivery, not a bad minute.
        """

        if not provider_order_id:
            raise DeliveryProviderError("No delivery named", retryable=False)
        self._call("POST", f"/v1.0/store/channel/vendor/{provider_order_id}/cancel")

    def parse_webhook(self, payload: dict[str, Any]) -> DeliveryResult:
        """Their webhook mirrors the status response, so one reader serves both."""

        return self._read(payload.get("data") or payload)

    def _read(self, data: dict[str, Any]) -> DeliveryResult:
        fulfillment = data.get("fulfillment")
        fulfillment = fulfillment if isinstance(fulfillment, dict) else {}
        rider = fulfillment.get("rider")
        rider = rider if isinstance(rider, dict) else {}
        fulfillment_status = fulfillment.get("status") or data.get("fulfillment_status")
        state = state_for(fulfillment_status, data.get("status"))
        # The pickup and drop blocks carry an `eta` from the moment a rider is
        # assigned, and a `timestamp` once the event has happened. Read from
        # the sandbox, not the Postman page: the fields this used to look for,
        # `picked_up_at` and `delivered_at`, are not anything Pidge sends.
        pickup = fulfillment.get("pickup") if isinstance(fulfillment.get("pickup"), dict) else {}
        drop = fulfillment.get("drop") if isinstance(fulfillment.get("drop"), dict) else {}
        timeline, located, failure = _timeline(fulfillment.get("logs"))
        return DeliveryResult(
            provider_order_id=str(data.get("id") or ""),
            state=state,
            reference=str(data.get("reference_id") or ""),
            rider_name=str(rider.get("name") or ""),
            rider_mobile=str(rider.get("mobile") or ""),
            tracking_url=_tracking_url(data, fulfillment),
            distance_metres=_float(data.get("pickup_drop_distance")),
            picked_up_at=_moment(pickup.get("timestamp")) or _moment(fulfillment.get("picked_up_at")),
            # The drop block gets a timestamp on an RTO too - the rider "dropped"
            # the food back at the restaurant. Only a delivery is a delivery.
            delivered_at=(
                _moment(drop.get("timestamp")) or _moment(fulfillment.get("delivered_at"))
                if state == DeliveryState.DELIVERED
                else None
            ),
            provider_status=str(fulfillment_status or data.get("status") or ""),
            raw=data,
            pickup_eta=_moment(pickup.get("eta")),
            drop_eta=_moment(drop.get("eta")),
            courier_charge=_money(fulfillment.get("delivery_charge")),
            rider_latitude=located[0] if located else None,
            rider_longitude=located[1] if located else None,
            rider_location_at=located[2] if located else None,
            failure_reason=failure if state == DeliveryState.FAILED else "",
            timeline=timeline,
        )


#: Where a trip went wrong, as opposed to a step along the way.
_FAILURE_STATUSES = {"UNDELIVERED", "RTO_OUT_FOR_DELIVERY", "RTO_UNDELIVERED", "RTO_DELIVERED", "LOST", "DAMAGED", "DISPOSED"}


def _timeline(
    logs: Any,
) -> tuple[list[dict[str, Any]], tuple[float, float, datetime | None] | None, str]:
    """The courier's steps, the rider's last known point, and why it failed.

    Pidge's `logs` hold every status with a time, a remark ("Start for
    Pickup", "Customer reject order - DRTO") and the rider's position at that
    moment. Returned oldest first. Duplicated statuses are kept: a rider who
    reached the door twice did reach it twice.
    """

    steps: list[dict[str, Any]] = []
    located: tuple[float, float, datetime | None] | None = None
    failure = ""
    for log in logs if isinstance(logs, list) else []:
        if not isinstance(log, dict):
            continue
        status = str(log.get("status") or "").strip().upper()
        if not status:
            continue
        at = _moment(log.get("timestamp"))
        remark = str(log.get("remark") or "").strip()
        steps.append({"status": status, "at": at.isoformat() if at else None, "remark": remark})
        where = log.get("location") if isinstance(log.get("location"), dict) else {}
        latitude, longitude = _float(where.get("latitude")), _float(where.get("longitude"))
        if latitude is not None and longitude is not None:
            located = (latitude, longitude, at)
        if status in _FAILURE_STATUSES and remark and not failure:
            failure = remark
    steps.sort(key=lambda step: step["at"] or "")
    return steps, located, failure


def _money(value: Any) -> Decimal | None:
    """A courier's price as Decimal, via str — never through float.

    `Decimal(71.26)` is 71.2599999... and money that arrives at a checkout
    three places wrong is money somebody has to explain.
    """

    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None


def _seconds(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _tracking_url(data: dict[str, Any], fulfillment: dict[str, Any]) -> str:
    """Where a customer watches the rider.

    Pidge does not send a URL. Their webhook carries a short code — `track_code`,
    something like "iaseov" — and the page is that code dropped into an address
    they publish. This used to look for a `tracking_url` field, which is not
    something they have ever sent, so the tracking link was always empty and
    nobody could tell whether that was a missing rider or a missing field.

    A literal URL still wins if one ever appears, because a URL they sent beats
    one we assembled.
    """

    for source in (fulfillment, data):
        literal = str(source.get("tracking_url") or "").strip()
        if literal:
            return literal

    for source in (fulfillment, data):
        code = str(source.get("track_code") or "").strip()
        if code:
            template = get_settings().pidge_tracking_url
            # Formatted by hand rather than with `.format`, so a stray brace in
            # a misconfigured template cannot raise inside a webhook.
            return template.replace("{code}", code)
    return ""


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


__all__ = ["PROVIDER_NAME", "PidgeProvider", "state_for"]
