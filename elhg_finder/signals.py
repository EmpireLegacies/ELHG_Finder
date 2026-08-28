"""Demand-signal patterns.

The premise of this tool: people reveal what they want to buy or learn by the
*shape* of the sentence they type, not by naming a product. "Does anyone know
how to..." is a demand signal. "Notion" is just a noun.

Each pattern carries a weight reflecting how close the phrasing sits to money
changing hands. A stated willingness to pay outranks idle curiosity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    """What the poster is actually revealing about themselves."""

    WILLING_TO_PAY = "willing_to_pay"        # strongest: money already in mind
    HIRING = "hiring"                        # wants to pay a person, right now
    UNMET_TOOL_NEED = "unmet_tool_need"      # wants a product that doesn't exist
    LEARNING = "learning"                    # wants a skill, will buy training
    HOW_TO = "how_to"                        # wants information, will buy a guide
    FRUSTRATION = "frustration"              # pain worth solving, not yet shopping
    FROM_HOME = "from_home"                  # topical: remote/home-based work
    MONETIZE = "monetize"                    # wants to turn a skill into income


#: Weight per intent. Feeds directly into the demand score, so the ordering here
#: is the editorial judgment of the whole tool.
INTENT_WEIGHT: dict[Intent, float] = {
    Intent.WILLING_TO_PAY: 5.0,
    Intent.HIRING: 4.5,
    Intent.UNMET_TOOL_NEED: 4.0,
    Intent.MONETIZE: 3.0,
    Intent.LEARNING: 2.5,
    Intent.HOW_TO: 2.0,
    Intent.FROM_HOME: 1.5,
    Intent.FRUSTRATION: 1.5,
}


@dataclass(frozen=True)
class Pattern:
    """One demand-signal phrasing.

    ``query`` is the quoted phrase handed to a search API. ``regex`` is the
    looser matcher run over text we already have in hand, so a body that says
    "I'd happily pay for" still scores even though we searched "would pay for".
    """

    intent: Intent
    query: str
    regex: str = ""

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.regex or re.escape(self.query), re.IGNORECASE)


PATTERNS: list[Pattern] = [
    # --- Money already on the table -------------------------------------
    Pattern(Intent.WILLING_TO_PAY, "I would pay for",
            r"\b(i|i'?d|we'?d|would)\s+(happily\s+|gladly\s+|definitely\s+)?pay\b"),
    Pattern(Intent.WILLING_TO_PAY, "shut up and take my money",
            r"take my money"),
    Pattern(Intent.WILLING_TO_PAY, "worth paying for",
            r"worth pay(ing)?\b"),
    Pattern(Intent.WILLING_TO_PAY, "is there a paid version",
            r"(paid|premium)\s+(version|option|tier|plan)\b"),

    # --- Actively looking to hire ---------------------------------------
    Pattern(Intent.HIRING, "looking to hire someone to",
            r"looking to (hire|pay|outsource)\b"),
    Pattern(Intent.HIRING, "can someone do this for me",
            r"(can|could)\s+(someone|somebody|anyone)\s+(do|make|build|set\s*up|handle)\b"),
    Pattern(Intent.HIRING, "where can I find someone who",
            r"where (can|do) i find (someone|somebody|a freelancer|a contractor)\b"),
    Pattern(Intent.HIRING, "need to outsource",
            r"need to (outsource|delegate|hand off)\b"),

    # --- The product does not exist yet ----------------------------------
    Pattern(Intent.UNMET_TOOL_NEED, "is there a tool that",
            r"is there (a|an|any)\s+(tool|app|service|software|template|program)\s+that\b"),
    Pattern(Intent.UNMET_TOOL_NEED, "I wish there was",
            r"(i )?wish (there (was|were)|someone (would|made))\b"),
    Pattern(Intent.UNMET_TOOL_NEED, "does anything exist that",
            r"does (anything|something|any\s+\w+) exist\b"),
    Pattern(Intent.UNMET_TOOL_NEED, "why is there no",
            r"why (is there|isn'?t there) (no|any)\b"),
    Pattern(Intent.UNMET_TOOL_NEED, "still doing this manually",
            r"(still )?doing (this|it|that) (manually|by hand)\b"),

    # --- Wants to turn something into income ------------------------------
    Pattern(Intent.MONETIZE, "how to monetize",
            r"how (do i|to|can i) monetiz\w*"),
    Pattern(Intent.MONETIZE, "turn this skill into income",
            r"turn (this|my|it) \w*\s?(skill|hobby|knowledge|experience) into\b"),
    Pattern(Intent.MONETIZE, "side hustle ideas",
            r"side (hustle|gig|income|business)\b"),
    Pattern(Intent.MONETIZE, "how do people make money doing",
            r"how (do|does) (people|anyone|you) (make|earn) money\b"),
    Pattern(Intent.MONETIZE, "is this a viable business",
            r"(viable|profitable|real) (business|income|market)\b"),

    # --- Wants to acquire a skill ----------------------------------------
    Pattern(Intent.LEARNING, "how do I learn",
            r"how (do|can|should) i learn\b"),
    Pattern(Intent.LEARNING, "best way to learn",
            r"best (way|resource|course|place) to learn\b"),
    Pattern(Intent.LEARNING, "is there a course for",
            r"is there (a|any) (course|class|training|certification|bootcamp)\b"),
    Pattern(Intent.LEARNING, "where do I start with",
            r"where (do|should) i (start|begin)\b"),
    Pattern(Intent.LEARNING, "resources for beginners",
            r"(resources?|guide|roadmap) for (beginners?|newbies?|someone new)\b"),
    Pattern(Intent.LEARNING, "worth learning in 2026",
            r"worth learning\b"),

    # --- Wants information ------------------------------------------------
    Pattern(Intent.HOW_TO, "how do I actually",
            r"how do i (actually|even)\b"),
    Pattern(Intent.HOW_TO, "step by step guide",
            r"step[- ]by[- ]step\b"),
    Pattern(Intent.HOW_TO, "can someone explain",
            r"(can|could) (someone|somebody|anyone) explain\b"),
    Pattern(Intent.HOW_TO, "what am I missing",
            r"what am i (missing|doing wrong)\b"),

    # --- Home / remote framing -------------------------------------------
    Pattern(Intent.FROM_HOME, "work from home business",
            r"(work|working|business|job|income)\s+(from|at)\s+home\b"),
    Pattern(Intent.FROM_HOME, "remote side business",
            r"remote (side )?(business|work|gig|job)\b"),
    Pattern(Intent.FROM_HOME, "start a business from home",
            r"start (a|my own) \w*\s?(business|service|agency) (from|at) home\b"),
    Pattern(Intent.FROM_HOME, "stay at home mom income",
            r"stay[- ]at[- ]home (mom|mum|dad|parent)\b"),

    # --- Pain worth solving ------------------------------------------------
    Pattern(Intent.FRUSTRATION, "biggest pain point",
            r"(biggest |main |worst )?pain point\b"),
    Pattern(Intent.FRUSTRATION, "wasting hours every week",
            r"wast(e|ing) (hours|time|so much time)\b"),
    Pattern(Intent.FRUSTRATION, "there has to be a better way",
            r"(there|has to be|must be) a better way\b"),
    Pattern(Intent.FRUSTRATION, "so frustrating",
            r"(so|really|incredibly) (frustrating|tedious|painful)\b"),
]


#: Topic seeds crossed with the patterns above to build search queries.
#: Deliberately broad: the point of the first sweep is to find out which of
#: these areas people are actually asking about, not to assume one.
DEFAULT_TOPICS: list[str] = [
    "virtual assistant",
    "bookkeeping",
    "freelance writing",
    "graphic design",
    "video editing",
    "social media management",
    "AI automation",
    "no code app",
    "spreadsheet automation",
    "notion template",
    "canva template",
    "digital product",
    "online course",
    "print on demand",
    "etsy shop",
    "dropshipping",
    "transcription",
    "proofreading",
    "resume writing",
    "grant writing",
    "voice over",
    "podcast editing",
    "web design",
    "SEO",
    "email marketing",
    "copywriting",
    "data entry",
    "customer support remote",
    "medical billing",
    "insurance claims",
    "tax preparation",
    "real estate virtual assistant",
    "photo editing",
    "3d modeling",
    "cad drafting",
    "technical writing",
    "translation",
    "online tutoring",
    "course creation",
    "membership site",
    "affiliate marketing",
    "youtube automation",
    "newsletter business",
    "consulting from home",
    "safety consulting",
    "compliance consulting",
    "HR consulting",
    "project management",
    "chatbot building",
    "prompt engineering",
]


def find_signals(text: str) -> list[tuple[Intent, str]]:
    """Return every (intent, matched phrase) present in ``text``.

    One hit per pattern; a body that repeats itself shouldn't outscore a body
    that makes the same point once.
    """
    if not text:
        return []
    hits: list[tuple[Intent, str]] = []
    seen: set[str] = set()
    for pattern in PATTERNS:
        match = pattern.compiled().search(text)
        if match and pattern.query not in seen:
            seen.add(pattern.query)
            hits.append((pattern.intent, match.group(0)))
    return hits


def build_queries(topics: list[str], intents: list[Intent] | None = None) -> list[str]:
    """Cross demand patterns with topic seeds into concrete search queries."""
    wanted = set(intents) if intents else set(Intent)
    queries: list[str] = []
    for pattern in PATTERNS:
        if pattern.intent not in wanted:
            continue
        for topic in topics:
            queries.append(f'"{pattern.query}" {topic}')
    return queries


def distinct_intents(signals: list) -> list[str]:
    """Unique intent names in first-seen order, for display.

    A post can trip three different "hiring" phrasings; that's one fact about
    the post, not three, so the badge row shouldn't repeat itself.
    """
    out: list[str] = []
    for entry in signals or []:
        name = entry[0] if isinstance(entry, (list, tuple)) else str(entry)
        if name not in out:
            out.append(name)
    return out
