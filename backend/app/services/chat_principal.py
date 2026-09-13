"""Who is asking the concierge — which is not always a signed-in customer.

The concierge is deliberately usable before login. A visitor can ask "something
spicy under 200" and get real menu rows back; the sign-in wall sits at checkout,
where it actually buys us something, not in front of browsing. Gating discovery
behind a login form is how you lose the customer before they ever see the food.

That means every RAG path which used to assume a `User` row must also serve
someone who has no row in `users`. Only `.id` is ever read off that object (31
sites in `rag.py` when this was written), so a guest gets a stable synthetic id
instead of a `user_id | None` threaded through the whole pipeline. Redis session
memory then works unchanged, and the diff stays off the hot path.

The one thing a guest must NOT get is a `chat_history` row: that table's
`user_id` is NOT NULL with an FK to `users`, so an insert would raise. Guest
turns are therefore memory-only — they live in Redis for the session TTL and
are gone after that. Losing an anonymous visitor's chat log costs nothing;
letting them use the concierge at all is the point.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models.user import User

# Fixed namespace so one chat session always maps to the same synthetic id,
# across processes and across restarts. A uuid4 per request would look fine in
# a single-turn test and silently reset the visitor's memory on every message.
GUEST_ID_NAMESPACE = uuid.UUID("9e0298a7-0436-4104-b8d0-af615d9b694a")


@dataclass(frozen=True)
class GuestPrincipal:
    """An unauthenticated visitor, shaped just enough to stand in for a User."""

    id: uuid.UUID
    is_guest: bool = True


ChatPrincipal = User | GuestPrincipal


def guest_principal_for_session(session_id: uuid.UUID) -> GuestPrincipal:
    """Derive a guest's id from the chat session they are already carrying.

    The caller must resolve the session id BEFORE calling this — passing None
    here and letting the pipeline invent its own session id downstream would
    put turn 1's memory under a key turn 2 never looks at.
    """

    return GuestPrincipal(id=uuid.uuid5(GUEST_ID_NAMESPACE, str(session_id)))


def is_guest(principal: ChatPrincipal) -> bool:
    return isinstance(principal, GuestPrincipal)
