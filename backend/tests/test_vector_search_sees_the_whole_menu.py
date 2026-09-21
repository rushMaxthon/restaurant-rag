"""A branch's own dishes must not be invisible to its own menu search.

Radhe Dhokla is a vegetarian kitchen in Surat. Asked for "red curry tofu" — a
dish it does not sell — the assistant answered "Which size for Kaju Curry
(Brown)?", offering a cashew curry under the name of a tofu one. Asked for
"chicken biryani" it offered Hydrabadi Biryani. A customer could pay for a dish
they never asked for.

There is a guardrail against exactly this (`apply_dish_name_guardrail`), and it
was not firing. Traced back, the reason was two layers below the wording:

    'tofu' embedded fine (768 dims, unit norm)
    platform-wide nearest : [('Tofu Larb', 0.313)]
    scoped to this branch : []          <-- no rows at all

An ORDER BY distance with a LIMIT and no cutoff cannot return nothing when the
branch has 136 embedded items. An APPROXIMATE index can. `menu_embeddings`
carries an IVFFlat index built `WITH (lists = 14)`, and the server's
`ivfflat.probes` was **1** — so a query scanned one list in fourteen, and the
restaurant/branch filter was applied to whatever that one list happened to
hold. For a query vector whose neighbourhood belongs to other restaurants'
dishes, this branch contributed nothing, and retrieval returned empty.

The guardrail reads an empty retrieval as `unknown` — "no evidence either way",
which is the correct reading of no evidence — and `_get_dish` then answered
with the fuzzy-name tier's nearest guess. So the honest "I don't have that"
was lost to a tuning constant.

Measured on this database, 1,332 embeddings platform-wide:

    probes=1     68.6ms   []
    probes=4    129.2ms   [Veg. Fried Rice 0.47, ...]
    probes=14    66.8ms   [Veg. Fried Rice 0.47, Tawa Pulao 0.484, ...]
    exact scan   67.1ms   [Veg. Fried Rice 0.47, Tawa Pulao 0.484, ...]

Full probing and an exact scan cost the same, because at this size the 67ms is
the round trip to Supabase and not the search. And with retrieval correct, the
nearest thing to "tofu" is 0.47, comfortably past the guardrail's 0.38 — so the
existing guardrail answers "absent" by itself, with no new rule needed.

This file guards the setting. The live behaviour is verified by
`scripts/flow_check.py`, which cannot run in a unit test: it needs a database,
an Ollama and a seeded tenant.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import database


class EveryNewConnectionProbesTheWholeIndexTests(unittest.TestCase):
    """The setting is per connection, so a missed connection is a silent gap."""

    def statements(self) -> list[str]:
        """What the connect listener runs, against a fake DBAPI connection."""

        cursor = mock.MagicMock()
        connection = mock.MagicMock()
        connection.cursor.return_value = cursor
        database.set_vector_probes(connection, None)
        return [call.args[0] for call in cursor.execute.call_args_list]

    def test_it_sets_the_probe_count(self) -> None:
        self.assertTrue(
            any("ivfflat.probes" in statement for statement in self.statements()),
            "a new connection kept the server default of 1 probe in 14 lists",
        )

    def test_the_count_is_high_enough_to_scan_every_list(self) -> None:
        # pgvector clamps `probes` to the index's list count, so a value larger
        # than any plausible `lists` means "scan them all" — which is what makes
        # this correct rather than merely better tuned. A value chosen to match
        # today's `lists = 14` would silently under-probe the first time anyone
        # rebuilt the index bigger.
        statement = next(s for s in self.statements() if "ivfflat.probes" in s)
        value = int(statement.rsplit("=", 1)[1].strip().rstrip(";"))
        self.assertGreaterEqual(value, 1000)

    def test_a_server_without_pgvector_still_connects(self) -> None:
        # The setting is unknown to a Postgres that has never loaded pgvector,
        # and a raising connect listener takes down every connection in the
        # pool — turning a search-quality fix into an outage.
        cursor = mock.MagicMock()
        cursor.execute.side_effect = Exception("unrecognized configuration parameter")
        connection = mock.MagicMock()
        connection.cursor.return_value = cursor
        database.set_vector_probes(connection, None)  # must not raise

    def test_the_cursor_is_closed(self) -> None:
        cursor = mock.MagicMock()
        connection = mock.MagicMock()
        connection.cursor.return_value = cursor
        database.set_vector_probes(connection, None)
        cursor.close.assert_called_once()

    def test_it_is_wired_to_the_engine(self) -> None:
        # A listener nothing registered is a comment with a test attached.
        from sqlalchemy import event

        self.assertTrue(
            event.contains(database.engine, "connect", database.set_vector_probes),
            "set_vector_probes is never called on a new connection",
        )


if __name__ == "__main__":
    unittest.main()
