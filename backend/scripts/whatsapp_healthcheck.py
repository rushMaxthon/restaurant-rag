"""Can this deployment still talk to Meta? A read-only check.

Sends nothing. It asks the Graph API to describe the number we answer for,
which is the cheapest call that exercises the same token and the same host
`send_text` uses — so a failure here is the failure a customer's message
would hit, several seconds earlier and without messaging anybody.

The token, the app secret and the verify token are never printed: only
whether they are set, and what Meta said about them.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "F:/restaurant-rag/backend")

import httpx

from app.config import get_settings

settings = get_settings()


def main() -> int:
    token = (settings.whatsapp_access_token or "").strip()
    number_id = (settings.whatsapp_phone_number_id or "").strip()

    print(f"enabled            : {settings.whatsapp_enabled}")
    print(f"phone_number_id    : {number_id or '(unset)'}")
    print(f"business number    : {settings.whatsapp_business_number or '(unset)'}")
    print(f"access token       : {'set, ' + str(len(token)) + ' chars' if token else 'UNSET'}")
    print(f"app secret         : {'set' if settings.whatsapp_app_secret else 'UNSET'}")
    print(f"allowed senders    : {settings.whatsapp_allowed_senders or '(everyone)'}")
    print(f"api base           : {settings.whatsapp_api_base_url}")
    print()

    if not token or not number_id:
        print("RESULT: cannot call Meta without both a token and a number id.")
        return 1

    url = f"{settings.whatsapp_api_base_url.rstrip('/')}/{number_id}"
    try:
        response = httpx.get(
            url,
            params={"fields": "display_phone_number,verified_name,quality_rating"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
    except httpx.HTTPError as error:
        print(f"RESULT: could not reach Meta at all — {type(error).__name__}: {error}")
        return 1

    print(f"GET {url}")
    print(f"status: {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        print(response.text[:400])
        return 1

    if response.status_code == 200:
        print(f"number      : {payload.get('display_phone_number')}")
        print(f"verified as : {payload.get('verified_name')}")
        print(f"quality     : {payload.get('quality_rating')}")
        print("\nRESULT: the token works and the number is reachable.")
        return 0

    error = payload.get("error", {})
    print(f"type        : {error.get('type')}")
    print(f"code        : {error.get('code')} (subcode {error.get('error_subcode')})")
    print(f"message     : {error.get('message')}")
    # The two that actually happen, named so nobody has to look them up.
    if error.get("code") == 190:
        print("\nRESULT: the ACCESS TOKEN is expired or invalid. A temporary token from")
        print("the Meta dashboard lasts 24 hours; a System User token does not expire.")
    elif error.get("code") in (100, 803):
        print("\nRESULT: the PHONE NUMBER ID does not match this token's app/account.")
    else:
        print("\nRESULT: Meta refused the call — see the message above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
