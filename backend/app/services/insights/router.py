"""Maps an owner's question onto one analysis skill and its parameters.

Rules first, model second. Most owner questions are formulaic ("how were sales
last week", "what's my best seller"), and matching them in code costs nothing —
which matters when the alternative is a second generation round-trip on a
CPU-only host.

Nothing the model returns is trusted directly: an unknown skill name is
discarded, and the date range is always parsed deterministically here rather
than taken from the model, so a hallucinated period can never silently change
which numbers an owner is shown.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.services.insights.periods import local_today
from app.services.insights.analyst.registry import TOOLS
from app.services.insights.analyst.schemas import ALLOWED_WINDOW_DAYS
from app.services.insights.multipart import decompose
from app.services.insights.skills import SKILL_NAMES, UNSUPPORTED_TOPICS, SkillParams

settings = get_settings()
logger = logging.getLogger(__name__)

from app.services.ollama_client import (
    think_option,
    GENERATE_ENDPOINT,
    build_client,
    local_only_options,
)

ROUTER_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=settings.ai_manager_router_timeout_seconds,
    write=10.0,
    pool=5.0,
)
ROUTER_CLIENT = build_client(ROUTER_TIMEOUT)


@dataclass(slots=True)
class RoutedQuestion:
    skill: str
    params: SkillParams
    # "rules" or "llm" — logged so the fallback rate can be tuned.
    source: str
    confidence: str = "high"


class LLMRoutePayload(BaseModel):
    skill: str
    metric: str | None = None
    subject: str | None = None


# Skills the planner must never choose, because each needs something the planner
# does not have:
#
# * `branch_comparison` needs the restaurant's real branch names, which only the
#   database knows, so the chat layer selects it after resolving the mention.
# * `tool_answer` carries a validated tool and arguments.
# * `multi_part` carries the parts the question decomposed into.
# * `small_talk` carries the opener that was detected. A planner reaching for it
#   on an odd data question would greet an owner who asked about revenue.
#
# All four are routed deterministically above; this only keeps them out of the
# planner's menu.
STRUCTURALLY_ROUTED_SKILLS = frozenset(
    {"branch_comparison", "tool_answer", "multi_part", "small_talk"}
)

# Common phrasings that a data tool answers directly. Matched before the skill
# patterns and before the unsupported topics, because both are looser: "how many
# orders failed at payment" contains the word "orders" and was answered with the
# total order count, up 1900%, which is precisely the confidently-wrong shape
# this work exists to remove.
#
# These cost nothing. A planner call is six to eight seconds warm and closer to
# thirty cold, so any question that can be recognised in code should be.
TOOL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "get_payment_health",
        (
            r"\b(card|stripe|online|wallet)\b.*\bpayments?\b.*\b(fail\w*|work\w*|declin\w*|issues?|problems?)\b",
            r"\b(payments?|stripe|gateway|provider)\b.*\b(provider|gateway|stripe|problems?|issues?|down|working)\b",
            r"\b(declin\w*|failure code)\w*\b.*\bpayments?\b",
        ),
    ),
    (
        "get_payment_failures",
        (
            r"\b(payments?|checkouts?)\b.*\b(fail\w*|declin\w*|abandon\w*|incomplete|never completed)\b",
            r"\b(fail\w*|declin\w*|abandon\w*)\b.*\b(payments?|checkouts?)\b",
            r"\borders?\b.*\bfail\w*\b.*\bpay\w*\b",
            r"\b(lost|lose|losing)\b.*\b(at|during|to)\b.*\b(payments?|checkouts?)\b",
        ),
    ),
    (
        "get_stockouts",
        (
            # Availability, not stock levels. "How much stock did I waste" stays
            # an honest refusal, because wastage genuinely is not recorded.
            r"\bout of stock\b",
            r"\b(sold|sell|selling|sells) out\b",
            r"\bran out\b",
            r"\b(switched|turned) off\b",
            r"\bunavailable\b",
            r"\b(items?|dish(es)?)\b.*\bavailability\b",
        ),
    ),
    (
        "get_branch_status",
        (
            r"\b(which|what|any)\b.*\bbranch\w*\b.*\b(closed|open|shut)\b",
            r"\bbranch\w*\b.*\b(currently|right now)\b.*\b(closed|open)\b",
            r"\b(is|are)\b.*\b(branch|location|outlet)\w*\b.*\b(open|closed|shut|trading)\b",
            r"\b(any|which|what)\b\s+(branch|location|outlet)\w*\b.*\b(shut|closed|open)\b",
        ),
    ),
    (
        "get_menu_health",
        (
            r"\bwhat.s on (my|the) menu\b",
            r"\bmenu\b.*\b(gaps?|missing|coverage)\b",
            r"\bhow many (items?|dishes)\b.*\bmenu\b",
            r"\bhow many\b.*\bmenu items?\b",
            r"\bhow (big|large)\b.*\bmenu\b",
        ),
    ),
    (
        "get_data_coverage",
        (
            r"\bhow many days\b.*\b(trade|traded|trading|orders?|open)\b",
            r"\btrading days\b",
            r"\bhow much data\b",
            r"\b(enough|sufficient) data\b",
        ),
    ),
    (
        "get_fulfillment_mix",
        (
            r"\b(delivery|deliveries)\b.*\b(vs|versus|against|or)\b.*\b(pickup|collection|takeaway|take-away)\b",
            r"\b(pickup|collection|takeaway)\b.*\b(vs|versus|against|or)\b.*\bdelivery\b",
            r"\bhow many\b.*\b(pickup|collect|takeaway|delivery)\w*\b",
            r"\b(scheduled|pre-?order\w*)\b.*\borders?\b",
            r"\b(do|are|how many)\b.*\b(customers?|people|they)\b.*\b(schedule|pre-?order|order in advance|order ahead)\w*\b",
            r"\b(percentage|percent|share|proportion|split|%)\b.*\b(pickup|delivery|collection|takeaway)\b",
            r"\b(pickup|delivery|collection|takeaway)\b.*\b(percentage|percent|share|proportion)\b",
            r"\b(delivery|pickup)\b.*\b(split|mix|share|breakdown)\b",
        ),
    ),
    (
        "get_payment_mix",
        (
            r"\bhow (do|are)\b.*\b(customers?|people|they)\b.*\bpay\w*\b",
            r"\bpayment\b.*\b(methods?|mix|split|types?)\b",
            r"\b(cash on delivery|cod|card|upi|google ?pay|wallet)\b.*\b(orders?|how many|share|used)\b",
            r"\bhow many\b.*\b(paid|pay)\b.*\b(cash|card|online)\b",
            r"\b(anyone|anybody|customers?|people)\b.*\bpay\w*\b.*\b(card|cash|cod|upi|wallet|google ?pay)\b",
            r"\b(card|cash|cod|upi|wallet|google ?pay)\b.*\b(payments?|orders?)\b.*\bhow many\b",
        ),
    ),
    (
        "get_order_economics",
        (
            r"\b(delivery fees?|tax|taxes)\b.*\b(collect\w*|paid|total|how much)\b",
            r"\bhow much\b.*\b(delivery fees?|tax|taxes|discounts?)\b",
            r"\b(fees?|discounts?)\b.*\b(given|paid out|total)\b",
            r"\bwhat.s in\b.*\border total\b",
            r"\b(makes? up|made up|breakdown of|composition of)\b.*\b(order )?totals?\b",
        ),
    ),
    (
        "get_offer_catalogue",
        (
            r"\boffers?\b.*\b(expire|expiry|expiring|expires|valid|validity)\b",
            r"\b(expire|expiry|expiring|expires)\b.*\boffers?\b",
            r"\b(live|active|running|ongoing|current)\b\s+(offers?|promotions?|discounts?)\b",
            r"\b(what|which|how many)\b.*\boffers?\b.*\b(do i have|are there|set up|exist)\b",
            r"\boffers?\b.*\b(currently (live|active|running)|still (live|active|running))\b",
            r"\b(offers?|promotions?|discounts?)\b\s+(are|is)\b.*\b(live|active|running|on)\b",
            r"\bdo i have\b.*\b(offers?|promotions?|discounts?)\b",
        ),
    ),
    (
        "get_combos",
        (
            r"\b(combos?|bundles?|meal deals?)\b",
            r"\bitems?\b.*\bordered together\b",
            r"\bwhat\b.*\bgoes with\b",
            r"\b(pairings?|pair together)\b",
        ),
    ),
    (
        "get_schedule",
        (
            r"\b(opening|closing) (hours?|times?)\b",
            r"\bwhat (time|hours)\b.*\b(open|close|closing)\b",
            r"\b(when|what time)\b.*\b(do|does)\b.*\b(we|i|the branch|the restaurant)\b.*\b(open|close)\b",
            r"\b(fulfil?lment|delivery|pickup) slots?\b",
            r"\b(advance|future) orders?\b.*\b(settings?|allowed|days?)\b",
            r"\bhow far (ahead|in advance)\b",
            r"\b(can|could)\b.*\b(customers?|people|they)\b.*\border\b.*\b(ahead|in advance)\b",
        ),
    ),
    (
        "get_notification_campaigns",
        (
            r"\b(push )?(notifications?|campaigns?)\b.*\b(sent|open\w*|deliver\w*|perform\w*|work\w*|results?)\b",
            r"\b(sent|send)\b.*\b(push )?notifications?\b",
            r"\bhow many\b.*\bnotifications?\b",
        ),
    ),
    (
        # After branch status, so "which branch is closed" keeps its own answer.
        "get_location_performance",
        (
            r"\b(each|every|all|per|by)\b\s+(branch|location|outlet|store)e?s?\b",
            r"\b(branch|location|outlet)e?s?\b.*\b(compare|comparison|perform\w*|doing|breakdown|split)\b",
            r"\bhow\b.*\b(are|is|did)\b.*\b(my |the )?(branch|location|outlet)e?s?\b.*\b(doing|perform\w*)\b",
            r"\brevenue\b.*\b(by|per)\b.*\b(branch|location|outlet)\b",
        ),
    ),
    (
        "get_daily_series",
        (
            r"\bday[- ]by[- ]day\b",
            r"\b(daily|per day|each day|every day)\b.*\b(revenue|sales|orders?|trade|breakdown|figures?)\b",
            r"\b(revenue|sales|orders?)\b.*\b(daily|per day|each day|by day)\b",
            r"\bwhich days?\b.*\b(busiest|best|worst|did|traded)\b",
            r"\bshow me\b.*\b(daily|day by day)\b",
        ),
    ),
    (
        "get_insight_history",
        (
            r"\b(what|which|any)\b.*\b(findings?|insights?)\b",
            r"\b(findings?|insights?)\b.*\b(raised|flagged|found|recent\w*)\b",
            r"\bwhat have you (found|flagged|noticed|spotted)\b",
        ),
    ),
    (
        "get_metric_deltas",
        (
            # Explicit comparison without a "why": the diagnosis rule owns "why".
            r"\bhow does\b.*\bcompare\b.*\b(previous|last|prior)\b",
            r"\bcompare\b.*\b(this|current)\b.*\b(week|month|period)\b.*\b(last|previous|prior)\b",
            r"\b(versus|vs)\b.*\b(last|previous|prior)\b\s*(week|month|period)\b",
            r"\bhow are\b.*\b(my )?numbers\b.*\b(compare|against|versus|vs)\b",
        ),
    ),
    (
        "get_period_metrics",
        (
            r"\b(all|overall|overview of)\b\s+(my )?(numbers|figures|totals|stats|metrics)\b",
            r"\b(my |the )?(totals|numbers|figures|stats|metrics)\b.*\b(for|last|this)\b\s+(week|month|period|\d+ days)\b",
            r"\bgive me\b.*\b(the )?(numbers|totals|figures|stats)\b",
        ),
    ),
    (
        "get_anomalies",
        (
            r"\b(unusual|abnormal|strange|odd|outlier)\w*\b.*\b(day|days)\b",
            r"\b(day|days)\b.*\b(unusual|abnormal|strange|odd|stood out|stand out)\w*\b",
            r"\b(any|which) day\b.*\b(stand out|stood out|unusual)\b",
            r"\banomal\w*\b",
        ),
    ),
)


# Ordered: the first pattern to match wins, so narrower intents are listed
# before the general revenue question.
SKILL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        # Compound: names a dish/decline *and* asks what promotion to run. Listed
        # first because either half alone would answer only part of it.
        "item_promotion_advice",
        (
            r"\b(items?|dish(es)?|products?|menu items?)\b.*\b(declin|fall|falling|fell|drop|down|slow|weak)\w*\b.*\b(promot\w*|offer|discount|deal)\b",
            r"\b(declin|fall|falling|fell|drop)\w*\b.*\b(items?|dish(es)?|products?)\b.*\b(promot\w*|offer|discount|deal)\b",
            r"\b(what|which)\b.*\b(promot\w*|offer|discount|deal)\b.*\b(declin|fall|falling|fell|drop|slow|weak)\w*\b",
        ),
    ),
    (
        # Ahead of the diagnosis rule, which would otherwise swallow "why were
        # orders cancelled" as a generic "why" question.
        "cancellation_reasons",
        (
            r"\bwhy\b.*\bcancell?",
            r"\bcancell?ation reasons?\b",
            r"\breasons?\b.*\bcancell?",
            r"\bcancell?(ed|ations?)\b.*\b(why|reason|cause)",
        ),
    ),
    (
        "action_outcomes",
        (
            r"\b(did|does|has)\b.*\b(my|the|that)\b.*\b(offer|action|recommendation|promotion)\b.*\b(work|help|pay|do anything)",
            r"\bdid it work\b",
            r"\b(outcome|result)s?\b.*\b(action|recommendation|offer)\b",
            r"\bwhat happened\b.*\b(offer|action|recommendation)\b",
            r"\bwas it worth it\b",
        ),
    ),
    (
        "order_operations",
        (
            r"\b(how (long|fast|quickly))\b.*\b(accept|prepare|prep|kitchen|order)",
            r"\b(acceptance|preparation|prep)\b.*\b(time|latency|speed)",
            r"\bkitchen\b.*\b(slow|fast|speed|time)",
            r"\border timings?\b",
        ),
    ),
    (
        "recommendations",
        (
            r"\bwhat should i (focus|work|concentrate) on\b",
            r"\bwhere should i focus\b",
            # Advice-seeking, not performance reporting.
            r"\b(what|which)\b.*\b(offer|promotion|discount|deal)s?\b.*\bshould i\b",
            r"\bshould i\b.*\b(run|offer|promote|discount)\b",
            r"\bwhat\b.*\b(promotion|offer|discount)\b.*\b(to )?run\b",
            r"\b(recommend|suggest)\w*\b.*\b(offer|promotion|discount)\b",
        ),
    ),
    (
        "offer_performance",
        (
            # Every pattern here carries performance intent. A bare mention of
            # "promotion" used to match, which sent "what promotion should I
            # run" to an ROI report instead of a recommendation.
            r"\boffers?\b.*\b(work|perform|worth|roi|result|effective)",
            r"\b(did|are|is|how are|how did)\b.*\boffers?\b.*\b(work|perform|do|doing|going)",
            r"\bdiscount(s|ing)?\b.*\b(work|worth|cost|roi)",
            r"\bpromotions?\b.*\b(work|perform|worth|roi|result|effective|doing|going)",
            r"\b(how (are|is|did|was))\b.*\bpromotions?\b",
            r"\boffer performance\b",
        ),
    ),
    (
        "recommendations",
        (
            r"\bwhat should i (focus|work|concentrate) on\b",
            r"\bwhere should i focus\b",
            r"\b(how|what)\b.*\b(increase|improve|grow|boost|lift)\b",
            r"\bwhat should i (do|try|change)\b",
            r"\brecommend(ation)?s?\b",
            r"\bsuggest(ion)?s?\b",
            r"\bideas?\b.*\b(sales|revenue|business)\b",
        ),
    ),
    (
        "customer_retention",
        (
            r"\b(repeat|returning|regular|loyal)\b.*\bcustomers?\b",
            r"\bnew customers?\b",
            r"\bcustomer (retention|churn|loyalty)\b",
            r"\blosing\b.*\bcustomers?\b",
            r"\bchurn\b",
            # "are customers coming back" is how an owner asks this, and it
            # matched nothing — so the commonest phrasing of a supported
            # question went to the planner and came back as a diagnosis.
            r"\bcustomers?\b.*\bcom(e|ing) back\b",
            r"\bcustomers?\b.*\breturn(ing)?\b",
            r"\bdo (my |the )?customers? (come|order) (back|again)\b",
            r"\bcustomers?\b.*\border(ing)? again\b",
            r"\bhow (are|is)\b.*\bcustomers?\b",
            r"\bcustomers?\b.*\b(doing|looking)\b",
        ),
    ),
    (
        "time_patterns",
        (
            r"\b(busiest|quietest|slowest|peak|off-peak)\b",
            r"\bwhat (time|day|hour)s?\b",
            r"\bwhen\b.*\b(busy|busiest|quiet|slow|orders?|sales)\b",
            r"\b(lunch|dinner|breakfast|evening|morning|weekend|weekday)\b.*\b(sales|orders|revenue|trade|perform)",
            r"\btime of day\b",
        ),
    ),
    (
        "item_performance",
        (
            r"\b(best|worst|top|bottom)[- ]?(selling|seller)",
            r"\bwhich (dish|item|product|food|menu item)",
            r"\b(dish|item|menu item)s?\b.*\b(selling|sell|perform|popular)",
            r"\bmost popular\b",
            r"\bcategory\b.*\b(perform|selling|sales)",
            # Ranking questions about the menu. These carry a direction word and
            # often the word "orders", which the metric rule would otherwise
            # claim — so they are matched here, where the direction is kept.
            r"\b(dish(es)?|items?|menu items?|products?)\b.*\b(fewest|least|lowest|worst|slowest|most|best|highest|biggest|top)\b",
            r"\b(fewest|least|lowest|worst|slowest|most|best|highest|biggest|top)\b.*\b(dish(es)?|items?|menu items?|products?)\b",
            r"\b(dish(es)?|items?|menu items?|products?)\b.*\b(drop|fell|fall\w*|declin\w*|grew|grow\w*|ris\w*)\b",
            r"\b(what|which)\b.*\b(isn.t|not|barely)\b.*\b(selling|sell|moving|ordered)\b",
        ),
    ),
    (
        "briefing_recall",
        (
            r"\b(summar(y|ise|ize)|recap|overview|briefing)\b",
            r"\bhow (are|is) (things|business|it) going\b",
            r"\bhow was (my|the) (week|month|day)\b",
        ),
    ),
    (
        "revenue_diagnosis",
        (
            r"\bwhy\b",
            r"\bwhat (happened|changed|caused)\b",
            r"\b(sales|revenue|business)\b.*\b(down|up|drop|fall|fell|rise|rose|declin|increas)",
            r"\b(down|up|drop|declin)\b.*\b(sales|revenue)",
            r"\bexplain\b",
            # A period-against-period question. It used to reach `time_patterns`
            # through the planner and come back describing dayparts, which is a
            # different question than the one asked.
            r"\bcompared? (it |this |that )?(to|with|against)\b.*\b(week|month|period|year|quarter)\b",
            r"\b(this|last) (week|month|quarter|year)\b.*\bvs\.?\b",
            r"\bhow did\b.*\bcompare\b",
            r"\bbetter or worse\b",
            # "How is the restaurant doing" — the broadest question an owner
            # asks, and it matched nothing at all.
            r"\bhow (is|are|was|were)\b.*\b(business|the restaurant|trading|sales|we doing)\b",
            # Deliberately NOT "how's it going": that is a greeting, and
            # claiming it here stopped the small-talk detector from seeing it.
            r"\bhow('| i)?s (business|trading)\b",
            r"\bhow are we doing\b",
            r"\bgive me (an? )?(overview|analysis|picture|summary of (trading|sales|performance))\b",
        ),
    ),
    (
        "metric_lookup",
        (
            r"\bhow (much|many)\b",
            # "revenue last week" — a metric named with a period and no verb.
            r"^(revenue|sales|turnover|orders|customers|items? sold|average order value|aov)\b[^?]{0,24}\b(today|yesterday|this week|last week|this month|last month|last \d+ days|between|from)\b",
            r"\bwhat (was|is|were)\b.*\b(revenue|sales|orders?|customers?|aov|average)",
            r"\btotal\b.*\b(revenue|sales|orders?)",
            r"\baverage order value\b",
            r"\bcancell?(ed|ations?)\b",
        ),
    ),
)

# --- what the question wants, beyond which analysis answers it ------------
#
# Routing alone was never enough. It picks the skill; these pick what the skill
# should say. Without them "which dishes sell least" and "which dishes had the
# biggest drop" both reached item performance and both got the same reply about
# the biggest earner, because nothing carried the difference between them.

# Which end of a ranking, or which direction of movement.
DIRECTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Movement first. "Biggest drop" contains both a magnitude word and a change
    # word, and the change is the more specific request: it asks about what
    # moved, not about what is largest.
    (
        "falling",
        (
            r"\b(drop(ped|ping|s)?|fell|fall(ing|en)?|declin\w*|decreas\w*)\b",
            r"\b(lost|losing|slipping|shrink\w*|worsen\w*)\b",
            r"\bdown\b",
        ),
    ),
    (
        "rising",
        (
            r"\b(grew|grow(ing|n|s)?|rise|rising|rose|increas\w*|climb\w*)\b",
            r"\b(gain(ed|ing|s)?|improv\w*|picking up)\b",
            r"\bup\b",
        ),
    ),
    (
        "bottom",
        (
            r"\b(fewest|least|lowest|worst|slowest|weakest|bottom|poorest)\b",
            # Apostrophes survive normalisation, so the contraction is matched
            # as written rather than assumed away.
            r"\b(is|are)n.?t (selling|moving|being ordered|ordered)\b",
            r"\bnot (selling|moving|ordered)\b",
            r"\bhardly (selling|moving|ordered)\b",
            r"\b(under[- ]?perform\w*|struggl\w*|unpopular)\b",
        ),
    ),
    (
        "top",
        (
            r"\b(most|best|top|highest|biggest|largest|strongest|greatest)\b",
            r"\b(popular|bestsell\w*|best[- ]sell\w*)\b",
        ),
    ),
)

# What the ranking is measured in. `None` means the skill uses its own default
# and says which one it used.
RANK_BASIS_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "orders",
        (
            r"\borders?\b",
            r"\border count\b",
            r"\btimes ordered\b",
            r"\bhow often\b",
            r"\boften\b",
            r"\bfrequency\b",
        ),
    ),
    (
        "quantity",
        (
            r"\bunits?\b",
            r"\bportions?\b",
            r"\bplates?\b",
            r"\bservings?\b",
            r"\bquantit(y|ies)\b",
        ),
    ),
    (
        "revenue",
        (
            r"\brevenue\b",
            r"\bsales\b",
            r"\bearn(ed|ings)\b",
            r"\bmoney\b",
            r"\bturnover\b",
        ),
    ),
)

EXPLICIT_LIMIT = re.compile(
    r"\b(?:top|bottom|best|worst|first)\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:worst|best|lowest|highest|slowest)\b"
)

# Things an owner may reasonably ask about that this platform does not model.
# Distinct from UNSUPPORTED_PATTERNS, which is about data that does not exist at
# all: these are cases where something adjacent *does* exist, so the refusal
# names it rather than leaving the owner guessing what to ask instead.
# Conversational openers, not questions about data. Matched before anything
# else, and kept deliberately tight: these fire on whole short messages rather
# than on a phrase appearing anywhere, so "how are you" is a greeting while
# "how are my sales" is not.
SMALL_TALK_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "how_are_you",
        (
            r"^how are (you|things|we)( doing| going)?\b",
            r"^how'?s it going\b",
            r"^you (ok|okay|alright|good|well)\b",
        ),
    ),
    (
        "thanks",
        (
            r"^(thanks|thank you|thankyou|ty|cheers|nice one|great|perfect|awesome)\b",
            r"^(that\'?s )?(helpful|useful|brilliant|lovely)\b",
        ),
    ),
    (
        "goodbye",
        (r"^(bye|goodbye|see you|good night|goodnight|later)\b",),
    ),
    (
        "capabilities",
        (
            r"\bwhat can you (do|help|tell|show)\b",
            r"\bwho are you\b",
            r"\bwhat are you\b",
            r"\bwhat do you do\b",
            r"\bhow (do|can) (i|you) (use|work)\b",
            r"^help$",
            r"^what can i ask",
        ),
    ),
    (
        "greeting",
        (
            r"^(hi|hey|hello|yo|hiya|howdy)\b",
            r"^good (morning|afternoon|evening|day)\b",
            r"^(hi|hey|hello) there\b",
        ),
    ),
)


def detect_small_talk(question: str) -> str | None:
    """Which conversational opener this is, if it is one at all.

    Long messages are excluded outright: "hello, why are my sales down?" is a
    question with a greeting attached, and answering the greeting would drop the
    question. Only a message that is *nothing but* an opener is small talk.
    """

    text = normalize(question).rstrip("?!. ")
    if len(text.split()) > 12:
        return None

    for intent, patterns in SMALL_TALK_PATTERNS:
        if not _matches(text, patterns):
            continue
        # "hello, why are my sales down?" opens with a greeting and then asks a
        # real question. Greeting it back would drop the question entirely, so
        # an opener only counts when there is no data question behind it.
        # "What can you do" is exempt: it is *about* the assistant, and naming
        # capabilities is the answer rather than a dodge.
        if intent != "capabilities" and _asks_about_data(text):
            return None
        return intent
    return None


def _asks_about_data(text: str) -> bool:
    """Whether anything in this message is a question about the restaurant."""

    for _, patterns in SKILL_PATTERNS:
        if _matches(text, patterns):
            return True
    for _, patterns in TOOL_PATTERNS:
        if _matches(text, patterns):
            return True
    for _, patterns in METRIC_PATTERNS:
        if _matches(text, patterns):
            return True
    return False


UNANSWERABLE_ENTITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "registered_users",
        (
            r"\b(registered|total|active|signed[- ]?up)\s+(users?|accounts?|members?)\b",
            r"\busers?\b.*\b(registered|signed up|total|active|count)\b",
            r"\bhow many (users?|accounts?|members?|sign[- ]?ups?)\b",
            r"\bapp users?\b",
        ),
    ),
    # `offer_validity` used to refuse here. Phase A reads both offer tables, so
    # the question has a real answer and the refusal was retired rather than
    # left to claim a question the system can now handle.
    (
        # Spend is the part that does not exist. Campaigns themselves do, and
        # `get_notification_campaigns` answers those — it is matched earlier, so
        # "how did my notifications perform" never reaches this.
        "marketing_spend",
        (
            r"\b(marketing|advertis\w*|ads?|campaigns?)\b.*\b(spend|spent|budget|costs?|roi|return)\b",
            r"\b(spend|spent|spending|budget)\b.*\b(marketing|advertis\w*|ads?|promotion)\b",
        ),
    ),
    (
        "reservations",
        (
            r"\b(reservations?|table bookings?|bookings?)\b",
            r"\bbook(ed|ing)? a table\b",
        ),
    ),
    (
        "refunds",
        (r"\brefund(s|ed|ing)?\b", r"\bchargebacks?\b"),
    ),
    (
        "delivery_partners",
        (
            r"\b(delivery (partner|driver|rider|agent)s?|couriers?)\b",
            r"\brider performance\b",
        ),
    ),
)


METRIC_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("average_order_value", (r"\baverage order value\b", r"\baov\b", r"\baverage order\b")),
    ("cancelled_orders", (r"\bcancell?(ed|ations?)\b",)),
    ("customers", (r"\bcustomers?\b", r"\bdiners?\b")),
    ("items_sold", (r"\bitems? sold\b", r"\bunits?\b")),
    ("orders", (r"\borders?\b",)),
    ("gross_revenue", (r"\brevenue\b", r"\bsales\b", r"\bturnover\b", r"\bearn(ed|ings)\b")),
)

UNSUPPORTED_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("reviews", (r"\breviews?\b", r"\bratings?\b", r"\bstars?\b", r"\bfeedback\b")),
    ("profit", (r"\bprofit(s|able|ability)?\b", r"\bmargins?\b", r"\bfood cost\b", r"\bcogs\b")),
    ("competitors", (r"\bcompetitors?\b", r"\bmarket share\b", r"\bother restaurants?\b", r"\brivals?\b")),
    ("staff", (r"\bstaff\b", r"\bemployees?\b", r"\blabou?r\b", r"\bshifts?\b", r"\brota\b")),
    # `cancellation_reasons` was refused here until Phase 6A began recording a
    # reason for every cancellation. It is answered by a real skill now.
    #
    # `stock` stays refused: knowing when a dish was switched off is not the
    # same as knowing stock levels or wastage.
    ("stock", (r"\bstock\b", r"\binventory\b", r"\bwastage\b", r"\bwaste\b", r"\bspoilage\b")),
)

RELATIVE_PERIODS: tuple[tuple[tuple[str, ...], int], ...] = (
    ((r"\bpast week\b", r"\bweekly\b", r"\bseven days\b"), 7),
    ((r"\blast (fortnight|two weeks)\b", r"\bfortnight\b", r"\btwo weeks\b"), 14),
    (
        (
            r"\blast month\b",
            r"\bthis month\b",
            r"\bmonthly\b",
            r"\bpast month\b",
            # Follow-ups say it this way: "and the month before?"
            r"\bmonth before\b",
            r"\bprevious month\b",
        ),
        30,
    ),
    ((r"\blast quarter\b", r"\bquarterly\b", r"\bthree months\b"), 90),
)

EXPLICIT_DAYS = re.compile(r"\blast (\d{1,3}) days?\b")


def normalize(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def detect_unsupported_topic(question: str) -> str | None:
    """Topics the platform holds no data for at all."""

    text = normalize(question)
    for topic, patterns in UNSUPPORTED_PATTERNS:
        if _matches(text, patterns):
            return topic
    return None


def detect_metric(question: str) -> str | None:
    text = normalize(question)
    for metric, patterns in METRIC_PATTERNS:
        if _matches(text, patterns):
            return metric
    return None


def detect_direction(question: str) -> str | None:
    """Which end of the ranking, or which way something moved.

    Order matters and is deliberate: a change word wins over a magnitude word,
    so "biggest drop" is a question about falling rather than about the largest
    anything. `DIRECTION_PATTERNS` is ordered to encode that.
    """

    text = normalize(question)
    for direction, patterns in DIRECTION_PATTERNS:
        if _matches(text, patterns):
            return direction
    return None


def detect_rank_basis(question: str) -> str | None:
    """What a ranking is measured in: money, order count, or units."""

    text = normalize(question)
    for basis, patterns in RANK_BASIS_PATTERNS:
        if _matches(text, patterns):
            return basis
    return None


def detect_limit(question: str) -> int | None:
    """An explicit "top 3" or "5 worst", capped so a question cannot ask for
    an unbounded list."""

    match = EXPLICIT_LIMIT.search(normalize(question))
    if match is None:
        return None
    raw = match.group(1) or match.group(2)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(1, min(value, 10))


def detect_unanswerable_entity(question: str) -> str | None:
    """Something the question is about that this platform does not model."""

    text = normalize(question)
    for entity, patterns in UNANSWERABLE_ENTITIES:
        if _matches(text, patterns):
            return entity
    return None


MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

# "1 June", "June 1", "1st June" — the halves of a range an owner types.
_DAY_MONTH = r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})"
_MONTH_DAY = r"([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?"
_ISO = r"(\d{4}-\d{2}-\d{2})"

RANGE_PATTERNS: tuple[str, ...] = (
    rf"(?:between|from)?\s*{_ISO}\s*(?:to|and|-|–|until)\s*{_ISO}",
    rf"(?:between|from)\s+{_DAY_MONTH}\s*(?:to|and|-|–|until)\s*{_DAY_MONTH}",
    rf"(?:between|from)\s+{_MONTH_DAY}\s*(?:to|and|-|–|until)\s*{_MONTH_DAY}",
    rf"{_DAY_MONTH}\s*(?:to|-|–|until)\s*{_DAY_MONTH}",
    rf"{_MONTH_DAY}\s*(?:to|-|–|until)\s*{_MONTH_DAY}",
)


def _named_date(first: str, second: str, today: date) -> date | None:
    """One half of a range, whichever way round the owner wrote it."""

    if first.isdigit():
        day, month_name = int(first), second
    else:
        day, month_name = int(second), first

    month = MONTHS.get(month_name.lower())
    if month is None:
        return None
    try:
        # No year given: assume the most recent one that has already happened,
        # so "1 June" in January means last June rather than a future date.
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    if candidate > today:
        try:
            candidate = date(today.year - 1, month, day)
        except ValueError:
            return None
    return candidate


def parse_explicit_range(question: str) -> tuple[date, date] | None:
    """An exact range the owner typed, or None if they typed no such thing."""

    text = normalize(question)
    today = local_today()

    for pattern in RANGE_PATTERNS:
        match = re.search(pattern, text)
        if not match:
            continue
        groups = [group for group in match.groups() if group]
        if len(groups) == 2 and all("-" in group for group in groups):
            try:
                start, end = date.fromisoformat(groups[0]), date.fromisoformat(groups[1])
            except ValueError:
                continue
        elif len(groups) == 4:
            start = _named_date(groups[0], groups[1], today)
            end = _named_date(groups[2], groups[3], today)
            if start is None or end is None:
                continue
        else:
            continue
        return (start, end) if start <= end else (end, start)
    return None


def parse_period(question: str, *, apply_default: bool = True) -> SkillParams:
    """Work out the window from the wording, in the restaurant's own timezone.

    Parsed in code rather than by the model: a hallucinated date range would
    silently answer a different question than the one asked.

    `apply_default=False` returns an empty period when the question named none,
    which is how a caller asks "did they state a period?" rather than "what
    period applies?". The follow-up layer needs that distinction: with the
    default applied, every follow-up looked like it had named a new window and
    inherited the previous analysis instead of routing itself.
    """

    text = normalize(question)
    today = local_today()

    # An exact range the owner typed wins over everything: they said precisely
    # what they wanted, and quietly measuring three months instead would be the
    # silent substitution this whole layer exists to avoid.
    explicit_range = parse_explicit_range(question)
    if explicit_range is not None:
        return SkillParams(date_from=explicit_range[0], date_to=explicit_range[1])

    if re.search(r"\byesterday\b", text):
        yesterday = today - timedelta(days=1)
        return SkillParams(date_from=yesterday, date_to=yesterday)

    if re.search(r"\btoday\b", text):
        return SkillParams(date_from=today, date_to=today)

    # Calendar weeks, because "this week" and "last week" are different weeks.
    # Both used to resolve to the same trailing seven days, so an owner asking
    # how last week went was shown a window that included most of this one.
    this_week_start = today - timedelta(days=today.weekday())

    if re.search(r"\bthis week\b", text):
        # Monday to today, today included. It used to stop at the last complete
        # day, so on a Monday "this week" answered for a week that had not
        # started and on any other day it left out the day being asked about.
        return SkillParams(date_from=this_week_start, date_to=today)

    if re.search(r"\blast week\b", text):
        last_week_end = this_week_start - timedelta(days=1)
        return SkillParams(
            date_from=last_week_end - timedelta(days=6), date_to=last_week_end
        )

    explicit = EXPLICIT_DAYS.search(text)
    if explicit:
        days = max(1, min(int(explicit.group(1)), settings.insights_max_window_days))
        return SkillParams(window_days=days)

    for patterns, days in RELATIVE_PERIODS:
        if _matches(text, patterns):
            return SkillParams(window_days=days)

    # Nothing named. "Which dish sells best?" is a question about the menu, not
    # about this week, and answering it from seven days ranked the menu on a
    # handful of orders. The default is stated in every reply, so an owner can
    # see the window they did not choose.
    if not apply_default:
        return SkillParams()
    return SkillParams(window_days=settings.ai_manager_chat_default_window_days)


# What answers a tool question when tool answers are switched off. Only where an
# existing skill genuinely covers the same ground: cancellations already report
# payments that never completed, so that question has a real answer either way.
# A tool with no equivalent falls through to the ordinary patterns.
TOOL_FALLBACK_SKILLS: dict[str, str] = {
    "get_payment_failures": "cancellation_reasons",
}


def detect_tool(question: str) -> str | None:
    """A data tool this question is asking for, recognised without a model."""

    text = normalize(question)
    for tool, patterns in TOOL_PATTERNS:
        if _matches(text, patterns):
            return tool
    return None


def route_with_rules(
    question: str, *, allow_tools: bool | None = None
) -> RoutedQuestion | None:
    """Match the question against known phrasings. None means the rules missed.

    `allow_tools` is passed by the chat layer, which knows the restaurant and
    therefore whether the tool path is live for it. Left unset it falls back to
    the global flag, so every other caller behaves exactly as before.
    """

    text = normalize(question)
    tools_live = (
        settings.enable_ai_manager_chat_tools if allow_tools is None else allow_tools
    )

    # Before the topics and the skills: both are looser, and either would claim
    # these questions and answer a different one.
    #
    # Detection is unconditional even though answering is flagged. A question
    # about payments failing matched the word "orders" and was reported as the
    # total order count, up 1900% — and a wrong answer should not be waiting
    # behind a feature flag for someone to turn off.
    tool = detect_tool(question)
    if tool is not None:
        params = parse_period(question)
        if tools_live:
            params.tool = tool
            params.tool_args = _tool_arguments(tool, question)
            return RoutedQuestion(skill="tool_answer", params=params, source="rules")

        fallback = TOOL_FALLBACK_SKILLS.get(tool)
        if fallback is not None:
            return RoutedQuestion(skill=fallback, params=params, source="rules")

        # No skill covers this one. Falling through would hand the question to
        # the looser patterns below, and "do more people order delivery or
        # pickup" would come back as a total order count — a wrong answer
        # produced only because a rollout flag was off.
        params.entity = "not_enabled_yet"
        return RoutedQuestion(skill="unsupported", params=params, source="rules")

    # Before every refusal: a greeting is not a question about data, so there
    # is nothing to refuse. Answering "hello" with "I could not work out which
    # part of your data that is about" is a bug, not an honest refusal.
    chatter = detect_small_talk(question)
    if chatter is not None:
        params = parse_period(question)
        params.topic = chatter
        params.subject = normalize(question)
        return RoutedQuestion(skill="small_talk", params=params, source="rules")

    topic = detect_unsupported_topic(question)
    if topic is not None:
        params = parse_period(question)
        params.topic = topic
        return RoutedQuestion(skill="unsupported", params=params, source="rules")

    # Before any skill matches: a question about something the platform does not
    # model must be refused by name. Left to the patterns below, "how many users
    # do we have" matched the metric rule and was answered with revenue.
    entity = detect_unanswerable_entity(question)
    if entity is not None:
        params = parse_period(question)
        params.entity = entity
        return RoutedQuestion(skill="unsupported", params=params, source="rules")

    # Before single-skill matching: a question asking for four things must not
    # be answered with the first one that matches a pattern. Refusals above
    # still win, so an unsupported topic is refused rather than composed.
    parts = decompose(question)
    if parts:
        params = parse_period(question)
        params.direction = detect_direction(question)
        params.rank_by = detect_rank_basis(question)
        params.limit = detect_limit(question)
        params.parts = tuple(part.key for part in parts)
        return RoutedQuestion(skill="multi_part", params=params, source="rules")

    for skill, patterns in SKILL_PATTERNS:
        if not _matches(text, patterns):
            continue
        params = parse_period(question)
        params.direction = detect_direction(question)
        params.rank_by = detect_rank_basis(question)
        params.limit = detect_limit(question)
        if skill == "metric_lookup":
            # No default. An unrecognised metric used to become revenue, which
            # answered a question nobody asked in the voice of one they did.
            params.metric = detect_metric(question)
        return RoutedQuestion(skill=skill, params=params, source="rules")

    return None


def _tool_arguments(tool: str, question: str) -> dict:
    """Arguments for a deterministically routed tool, from its own schema.

    Built by asking the tool what it declares rather than assuming every tool
    takes a window. `get_insight_history` takes a limit, and passing it
    `window_days` made a correctly routed question fail validation and answer
    "I could not look that up."
    """

    fields = TOOLS[tool].args_model.model_fields
    if "window_days" not in fields:
        return {}
    return _tool_window(question)


def _tool_window(question: str) -> dict:
    """The tool's window argument, taken from the question's own period words.

    Snapped to the allowed set rather than passed through: a tool refuses an
    unlisted window, and refusing an owner because they said "last 45 days" is a
    worse answer than measuring the nearest window and saying which one.
    """

    parsed = parse_period(question)
    if parsed.window_days:
        candidates = [days for days in ALLOWED_WINDOW_DAYS if days >= parsed.window_days]
        return {"window_days": candidates[0] if candidates else ALLOWED_WINDOW_DAYS[-1]}
    if parsed.date_from and parsed.date_to:
        span = (parsed.date_to - parsed.date_from).days + 1
        candidates = [days for days in ALLOWED_WINDOW_DAYS if days >= span]
        return {"window_days": candidates[0] if candidates else ALLOWED_WINDOW_DAYS[-1]}
    return {"window_days": settings.ai_manager_chat_default_window_days}


def build_router_prompt(question: str) -> str:
    skills = "\n".join(f"- {name}" for name in SKILL_NAMES)
    return f"""You are routing a restaurant owner's question to one analysis.

Return STRICT JSON only with this exact shape:
{{
  "skill": "string",
  "metric": "string or null",
  "subject": "string or null"
}}

The skill must be exactly one of:
{skills}

Guidance:
- revenue_diagnosis: why numbers changed
- metric_lookup: a single figure, with "metric" one of gross_revenue, orders,
  average_order_value, customers, items_sold, cancelled_orders
- item_performance: dishes or categories; "subject" may name one dish
- time_patterns: busy or quiet times and days
- customer_retention: new versus returning customers
- offer_performance: whether offers or discounts paid off
- recommendations: what the owner should do
- briefing_recall: a general summary
- unsupported: anything about reviews, ratings, profit, food cost, competitors,
  staff, or stock, none of which are recorded

Question: {question}

Return the JSON now.
"""


def _call_router_model(prompt: str) -> str:
    payload = {
        "model": settings.ai_manager_narration_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        **think_option(),
        **local_only_options(),
        "options": {
            "temperature": 0.0,
            "num_predict": settings.ai_manager_router_max_tokens,
        },
    }
    response = ROUTER_CLIENT.post(GENERATE_ENDPOINT, json=payload)
    response.raise_for_status()
    return str(response.json().get("response") or "")


def _extract_json(raw_reply: str) -> dict:
    raw_reply = raw_reply.strip()
    if not raw_reply:
        raise ValueError("Empty routing response")
    try:
        payload = json.loads(raw_reply)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = raw_reply.find("{")
    end = raw_reply.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object found in routing response")
    payload = json.loads(raw_reply[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Routing response JSON was not an object")
    return payload


def route_with_model(question: str) -> RoutedQuestion | None:
    """Ask the model which analysis fits. None means it could not be trusted."""

    try:
        parsed = LLMRoutePayload.model_validate(
            _extract_json(_call_router_model(build_router_prompt(question)))
        )
    except (httpx.TimeoutException, httpx.HTTPError, ValidationError, ValueError) as error:
        logger.warning("Question routing failed, using the default analysis: %s", error)
        return None

    skill = parsed.skill.strip()
    if skill not in SKILL_NAMES:
        # The model invented an analysis that does not exist. Executing anything
        # on that basis would be guesswork.
        logger.warning("Question routing returned unknown skill=%r", skill)
        return None

    params = parse_period(question)
    # Parsed from the question in code, never taken from the model: these decide
    # what the answer says, and a hallucinated one answers a question nobody
    # asked.
    params.direction = detect_direction(question)
    params.rank_by = detect_rank_basis(question)
    params.limit = detect_limit(question)
    params.entity = detect_unanswerable_entity(question)

    if skill == "metric_lookup":
        # No default. The model may name a metric, but only one that this
        # question's own words support is accepted.
        params.metric = detect_metric(question)
    if skill == "item_performance" and parsed.subject:
        params.subject = parsed.subject.strip()[:120]
    if skill == "unsupported":
        # Only a topic the question itself supports. This previously fell back to
        # `next(iter(UNSUPPORTED_TOPICS))` — the first key in the dict — so any
        # question the model called unsupported was reported as being about
        # customer reviews, including one about offer expiry dates.
        params.topic = detect_unsupported_topic(question)

    return RoutedQuestion(skill=skill, params=params, source="llm")


def route_question(
    question: str,
    *,
    allow_model: bool | None = None,
    allow_tools: bool | None = None,
) -> RoutedQuestion:
    """Pick the analysis for a question, always returning something usable.

    `allow_tools` has to be carried here as well as into `route_with_rules`.
    Without it this fell back to the global flag, and a restaurant outside the
    rollout list reached the tool path through the fallback that was supposed to
    be the safe route.
    """

    routed = route_with_rules(question, allow_tools=allow_tools)
    if routed is not None:
        return routed

    use_model = (
        settings.enable_ai_manager_chat_llm_router if allow_model is None else allow_model
    )
    if use_model:
        routed = route_with_model(question)
        if routed is not None:
            return routed

    # Nothing matched and the model could not help. A diagnosis is the most
    # broadly useful answer, and it is marked low confidence so the reply can
    # say what it assumed.
    return RoutedQuestion(
        skill="revenue_diagnosis",
        params=parse_period(question),
        source="rules",
        confidence="low",
    )


__all__ = [
    "STRUCTURALLY_ROUTED_SKILLS",
    "RoutedQuestion",
    "build_router_prompt",
    "detect_metric",
    "detect_unsupported_topic",
    "normalize",
    "parse_period",
    "route_question",
    "route_with_model",
    "route_with_rules",
]
