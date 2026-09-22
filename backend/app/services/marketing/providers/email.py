"""Email, over the restaurant's own SMTP.

SMTP rather than a vendor API for the same reason the SMS provider takes a
URL: every mail service speaks it, so an owner on SendGrid, Amazon SES,
Postmark or their host's own server can all connect without this codebase
knowing which. `smtplib` is in the standard library, so the channel costs the
deployment nothing.

**Every email carries an unsubscribe link.** It is a legal requirement and it
is generated per recipient from the same HMAC token the hosted unsubscribe
page already verifies — the one built for exactly this in the P1 work, where
the note said it would be reused for email. GET renders a confirmation and
only POST opts anyone out, which is what makes it safe to put in a mail body
that link scanners will fetch unattended.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings
from app.models.enums import MarketingChannel
from app.services.marketing.providers.base import (
    BatchMember,
    BatchResult,
    MemberOutcome,
    ProviderError,
    RenderedMessage,
)

logger = logging.getLogger(__name__)
settings = get_settings()


#: Domains that can never receive mail, and must not be attempted.
#:
#: The first four are reserved by RFC 2606 and RFC 6761 precisely so that
#: nothing tries to deliver to them; `.local` is mDNS. Every seeded account in
#: this product uses `example.com`, which is how a test send ended up being
#: posted to Gmail, accepted, and bounced back to the sending mailbox minutes
#: later — the owner got a bounce for an address they had never typed.
#:
#: Refusing up front is better than letting it bounce for two reasons: the
#: owner gets an immediate, accurate message instead of a delayed and
#: confusing one, and repeated bounces to a dead domain are exactly what
#: damages a sending reputation.
UNDELIVERABLE_SUFFIXES = (
    ".example",
    ".invalid",
    ".test",
    ".local",
    ".localhost",
)
UNDELIVERABLE_DOMAINS = frozenset(
    {"example.com", "example.org", "example.net", "localhost"}
)


def undeliverable_reason(address: str) -> str | None:
    """Why this address can never receive mail, or None if it might.

    Deliberately narrow: it rejects only domains that are reserved as
    undeliverable by standard, never a domain that merely looks unusual.
    Guessing that a real address is fake and refusing to send to it would be
    a worse failure than the bounce this prevents.
    """

    cleaned = (address or "").strip().lower()
    if "@" not in cleaned:
        return f"{address} is not an email address."
    domain = cleaned.rsplit("@", 1)[-1]
    if domain in UNDELIVERABLE_DOMAINS or domain.endswith(UNDELIVERABLE_SUFFIXES):
        return (
            f"{address} cannot receive mail — {domain} is a reserved example "
            "domain with no mail server. It is almost certainly a seeded test "
            "account rather than a real inbox."
        )
    return None


class EmailProvider:
    channel = MarketingChannel.EMAIL

    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._from_email = str(config.get("from_email") or "").strip()
        self._from_name = str(config.get("from_name") or "").strip()
        self._host = str(config.get("smtp_host") or "").strip()
        self._port = int(str(config.get("smtp_port") or "587") or 587)
        self._username = str(config.get("smtp_username") or "").strip()
        self._password = str(credentials.get("smtp_password") or "")
        if not self._from_email or not self._host:
            raise ProviderError(
                "Email is not finished connecting — it still needs a from-address and "
                "a mail server."
            )

    def addresses_for(self, user) -> list[str]:
        address = (getattr(user, "email", None) or "").strip()
        return [address] if "@" in address else []

    def max_batch(self) -> int:
        # One SMTP connection is opened per batch and reused for everyone in
        # it, so this trades connection churn against how often the progress
        # bar moves.
        return 100

    def send(self, members: list[BatchMember], *, message: RenderedMessage) -> BatchResult:
        outcomes: list[MemberOutcome] = []
        unsubscribe_urls = message.extra.get("unsubscribe_urls") or {}

        try:
            server = self._connect()
        except Exception as exc:  # noqa: BLE001 - the whole batch is affected
            raise ProviderError(
                f"Could not reach your mail server: {exc}", retryable=True
            ) from exc

        try:
            for member in members:
                address = member.addresses[0] if member.addresses else None
                if not address:
                    outcomes.append(
                        MemberOutcome(
                            user_id=member.user_id,
                            delivered=False,
                            reason="No email address on file",
                        )
                    )
                    continue
                try:
                    server.send_message(
                        self._build(
                            to=address,
                            message=message,
                            unsubscribe_url=unsubscribe_urls.get(str(member.user_id)),
                        )
                    )
                    outcomes.append(MemberOutcome(user_id=member.user_id, delivered=True))
                except smtplib.SMTPRecipientsRefused:
                    # The mailbox does not exist. Retiring the address stops
                    # every future campaign reporting the same bounce.
                    outcomes.append(
                        MemberOutcome(
                            user_id=member.user_id,
                            delivered=False,
                            reason="That mailbox does not exist",
                            dead_addresses=[address],
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - one bad address, not the batch
                    outcomes.append(
                        MemberOutcome(
                            user_id=member.user_id,
                            delivered=False,
                            reason=str(exc)[:255],
                        )
                    )
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001 - closing is best-effort
                logger.debug("SMTP quit failed", exc_info=True)

        return BatchResult(outcomes=outcomes)

    def _connect(self) -> smtplib.SMTP:
        server = smtplib.SMTP(self._host, self._port, timeout=settings.marketing_provider_timeout_seconds)
        server.ehlo()
        # STARTTLS where the server offers it. Not conditional on the port:
        # 587 is the convention, not the rule, and sending credentials in the
        # clear because someone used 2525 would be our fault, not theirs.
        if server.has_extn("starttls"):
            server.starttls()
            server.ehlo()
        if self._username:
            server.login(self._username, self._password)
        return server

    def _build(self, *, to: str, message: RenderedMessage, unsubscribe_url: str | None) -> EmailMessage:
        mail = EmailMessage()
        mail["Subject"] = message.title
        mail["From"] = f"{self._from_name} <{self._from_email}>" if self._from_name else self._from_email
        mail["To"] = to

        body = message.body
        if unsubscribe_url:
            body = f"{body}\n\n—\nDon't want these? {unsubscribe_url}"
            # The header mail clients read to offer their own unsubscribe
            # button. One-Click is declared only for POST, which is what the
            # hosted page requires — a scanner following the GET cannot opt
            # anybody out.
            mail["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            mail["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        mail.set_content(body)
        return mail
