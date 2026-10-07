"""Security headers on every API response.

Found in the 2026-10-07 security review: the API sent none. Only the compose
nginx added them, and production (Render) does not run it. What each one is
for:

- `X-Content-Type-Options: nosniff` - a JSON body is never run as a script or
  page because a browser guessed it was one.
- `X-Frame-Options: DENY` and CSP `frame-ancestors 'none'` - no other site
  can frame a response (clickjacking).
- CSP `default-src 'none'` outside local - an API response loads nothing.
  Local development keeps /docs working, which needs scripts.
- `Referrer-Policy: no-referrer` - a URL carrying an id or token is not
  handed to whatever the next page links to.
- `Strict-Transport-Security` outside local - browsers only ever use https
  for this host. Never on localhost, where it would pin every local app.
- `Cache-Control: no-store` on any request that carried a login - orders,
  addresses and payouts are never kept by a shared or browser cache. A
  response that set its own caching keeps it.

A plain ASGI middleware rather than Starlette's `BaseHTTPMiddleware`, which
buffers responses: the chat endpoints stream tokens one at a time.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_ALWAYS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]
_CSP_LOCAL = b"frame-ancestors 'none'"
_CSP = b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
_HSTS = (b"strict-transport-security", b"max-age=63072000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, local: bool) -> None:
        self.app = app
        self.local = local

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        signed_in = any(name == b"authorization" for name, _ in scope.get("headers", []))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                for name, value in _ALWAYS:
                    if name not in present:
                        headers.append((name, value))
                if b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", _CSP_LOCAL if self.local else _CSP))
                if not self.local and _HSTS[0] not in present:
                    headers.append(_HSTS)
                if signed_in and b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
