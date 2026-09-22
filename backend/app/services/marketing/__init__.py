"""The Marketing Hub's backend.

Layering, and why it is split this way:

* `consent.py` — who has agreed to hear from a restaurant. Read by everything
  below it, written only by the customer.
* `catalog.py` — the fixed reference data a campaign is assembled from: goals,
  segment definitions, branches, offers, message templates.
* `segments.py` — turns a segment key into real customers, scoped to one
  restaurant, its app client and a set of branches.
* `reach.py` — how many of those customers can actually be reached per channel,
  and every pre-send check that could stop or qualify the send.
* `campaigns.py` — persistence and lifecycle for the campaign itself.

The split matters because reach is re-computed server-side at dispatch, not
trusted from the draft the UI submitted. `reach.py` therefore has to be
callable without a campaign row existing, which is why it does not live inside
`campaigns.py`.
"""

from __future__ import annotations
