"""Whether the server may send a request to a URL somebody typed.

Found in the 2026-10-07 security review: an owner's SMS gateway `api_url` was
stored as typed and POSTed to from inside the platform's network, and the
start of whatever answered was shown back to them. Pointed at a loopback
port, a private Render address or the cloud metadata service, that is a way
to read the inside of the network.

`require_public_https` allows https only, no credentials in the URL, and a
host every one of whose addresses is public. Call it when the URL is saved
AND immediately before each request: a domain can be re-pointed at an
internal address after it was accepted (DNS rebinding), so the check that
counts is the one at send time. The caller must also not follow redirects -
httpx's default, which every caller here keeps.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeUrl(ValueError):
    """The URL may not be called; the message is written for an owner."""


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def require_public_https(url: str) -> str:
    text = (url or "").strip()
    parts = urlsplit(text)
    if parts.scheme != "https":
        raise UnsafeUrl("The address must start with https://")
    if parts.username or parts.password:
        raise UnsafeUrl("Put the API key in its own field, not in the address.")
    host = parts.hostname
    if not host:
        raise UnsafeUrl("That address has no host name.")
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as error:
        raise UnsafeUrl(f"{host} could not be found. Check the address.") from error
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_is_public(address) for address in addresses):
        raise UnsafeUrl(f"{host} is not a public internet address, so it cannot be used.")
    return text


__all__ = ["UnsafeUrl", "require_public_https"]
