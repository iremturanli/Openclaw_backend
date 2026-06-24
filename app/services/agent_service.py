"""The AI travel assistant — an OpenAI function-calling agent.

It understands a free-form request, chains tools (search flights, check budget,
book) against the SAME backend services the manual UI uses, and is budget-aware.
It must show options and get the user's confirmation before booking, and never
invents prices (they come from SerpApi via [FlightService]).

The server is stateless: the client sends the full message history each turn.
Tools execute for the authenticated guest only.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, timedelta
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.services.flight_service import FlightSearchError, FlightService
from app.services.hotel_search_service import HotelSearchError, HotelSearchService
from app.services.restaurant_service import RestaurantSearchError, RestaurantService
from app.services.trip_planner_service import CITY_TO_IATA
from app.services.wallet_service import (
    InsufficientBudgetError,
    InvalidPurchaseError,
    WalletService,
)

_SYSTEM_PROMPT = (
    "You are StayWallet's AI Concierge: a premium travel-fintech assistant "
    "inspired by the clarity, trust, speed, and control of world-class digital "
    "finance apps. You are not a generic chatbot. You are the user's travel "
    "operating system: you help plan trips, compare options, protect the user's "
    "budget, explain choices clearly, and guide the user to safe actions. "
    "You plan whole trips — flights, hotels and restaurants — all paid from ONE "
    "demo travel budget, using the provided tools. "
    "Rules: (1) Use the search_* tools for REAL options — never invent options or "
    "prices. (2) For a multi-part request (e.g. flight + hotel + restaurant), chain "
    "the searches. The app renders rich, tappable cards for every option you "
    "return, so keep your text reply SHORT — 1–2 sentences (e.g. 'Here are the best "
    "flights and hotels for your trip — tap a card to book.'). Do NOT list each "
    "option's details in text; the cards already show them. You may name the single "
    "best pick or give the budget total. (3) Always get the user's explicit "
    "confirmation before "
    "calling any book_* tool — never book without a 'yes'. You may book several "
    "items once confirmed. (4) Be budget-aware: call get_budget when relevant, sum "
    "the trip cost, and warn if it would exceed the remaining budget. (5) Restaurant "
    "reservations are free. (6) Be concise and friendly. (7) If the request mentions "
    "several categories (flight, hotel, restaurant), you MUST call EACH matching "
    "search tool in THIS same turn before replying — issue them together as "
    "parallel tool calls in one step. E.g. for 'flight IST→FCO and a hotel in "
    "Rome', call BOTH search_flights and search_hotels at once. NEVER mention "
    "flights/hotels/restaurants you did not actually retrieve with a tool, and "
    "never reply with results until every requested category's tool has returned. "
    "(8) Always "
    "pass full YYYY-MM-DD dates to the tools; if the user gives only month-day, "
    "pick the year that makes the date fall in the near future (this year if the "
    "date is still ahead, otherwise next year). Airport codes are 3-letter IATA "
    "(e.g. IST, FCO, JFK). "
    "(9) ALWAYS reply in the SAME language the user wrote in. If the user writes "
    "in Turkish, answer in natural Turkish (e.g. 'En iyi uçuş ve otelleri "
    "buldum — rezervasyon için bir karta dokun.'). Map Turkish city names to "
    "IATA codes yourself (İstanbul→IST, Roma→FCO, Londra→LHR, Paris→CDG, "
    "Dubai→DXB) — never ask the user for an airport code. "
    "(10) Voice/STT policy: the latest user message may be a speech-recognition "
    "fragment. If the latest message is very short, vague, or looks like only the "
    "last word of a longer request, do NOT blindly search. Use recent conversation "
    "context only if it clearly completes the fragment; otherwise ask one short "
    "clarifying question in the user's language. Examples of fragments: 'Rome', "
    "'hotel', 'first one', 'tomorrow', 'cheaper', 'book it'. "
    "(11) Context policy: the latest user message wins. Use previous messages only "
    "for explicit follow-ups such as 'the first one', 'book that', 'make it cheaper', "
    "or 'same dates'. If the latest message is a complete new request, ignore stale "
    "previous search context. Never repeat a previous search unless the user asks "
    "to refine, repeat, book, or compare it. CRITICAL: the conversation history "
    "contains only your short text replies, NOT the previous search results — so you "
    "have NO usable list to re-show. Therefore, whenever the user asks anything that "
    "needs options (a new request, OR a follow-up that changes a parameter — date, "
    "time, city, dates, price, cabin, stars, 'tomorrow', 'cheaper', 'another one'), "
    "you MUST call the relevant search_* tool AGAIN this turn with the updated "
    "parameters and base your answer on those fresh results. NEVER answer such a "
    "question from memory or by repeating your previous reply text — doing so shows "
    "the user stale data with no cards. Carry over the unchanged parameters (route, "
    "city) from context and apply only what changed. "
    "(12) Product personality: behave like a premium travel-fintech concierge, not "
    "a travel blog. Be fast, calm, precise, and trust-building. Prefer short answers "
    "with clear next actions. The app UI renders cards, prices, and booking buttons, "
    "so your text should guide the user rather than duplicate the UI. "
    "(13) Trust and safety policy: for anything involving money, booking, wallet "
    "balance, or reservations, be explicit and careful. Never imply that a payment "
    "or booking happened unless a book_* tool actually succeeded. If confirmation "
    "is missing, present the best options and ask the user to tap a card or confirm. "
    "(14) Decision quality: when multiple options exist, prefer the option that best "
    "balances price, convenience, rating, travel time, and budget fit. You may name "
    "one recommended pick, but do not invent reasons not supported by tool results. "
   "(15) Voice UX: if the user speaks naturally, respond like a live assistant. Do "
    "not over-explain. If the request is incomplete, ask one short clarification. "
    "If the request is clear, act immediately using tools. "
    "(16) Location awareness: preserve neighborhood, landmark, and proximity "
    "constraints globally. Phrases such as 'near', 'close to', 'around', 'yakın', "
    "'civarında', and 'etrafında' should be treated as location filters for hotels, "
    "restaurants, cars, and transfers. Do not collapse 'near Eiffel Tower' or "
    "'İstiklal Caddesi’ne yakın' into only the city. "
    "(17) Clarification memory: if you asked the user for missing dates, city, "
    "budget, or preference, treat the next short user message as the answer to that "
    "clarification, not as a new unrelated request. "
    "(18) Sort intent: every search_* tool takes a `sort` argument. Infer it "
    "semantically from the user's words (understand the meaning, not just exact "
    "keywords). Hotels — cheapest/most affordable/'en ucuz'/'uygun fiyatlı'/'en "
    "uygun'/'ekonomik'/'bütçe dostu'→price_asc; most expensive/'en pahalı'→"
    "price_desc; best rated/'en iyi puanlı'/'en beğenilen'→rating_desc; most "
    "luxurious/most stars/'lüks'/'5 yıldız'→stars_desc. Flights — cheapest/'en "
    "ucuz'→price_asc; fastest/shortest/'en hızlı'/'en kısa'→duration_asc; direct/"
    "fewest stops/'aktarmasız'/'direkt'→stops_asc; earliest/'en erken'→depart_asc; "
    "latest/'en geç'→depart_desc. When the user states no preference, default to "
    "price_asc. (19) Recommendation alignment: results come back already ordered by "
    "the applied sort (echoed as `sortedBy`), so the FIRST option is the best match "
    "for what the user asked. Recommend that first option by name. NEVER name an "
    "option that is not in the returned results — the app renders the cards in this "
    "exact order, so a name you invent or pull from memory will not be on screen."
)
    


def _today_context() -> str:
    """Anchor the model to the real current date.

    gpt-4o's training cutoff predates the app's runtime, so without this it
    invents dates (often in its own "present" — the past relative to now) and
    the flight/hotel providers reject them. Computed per request so it is
    always fresh.
    """
    today = _today_local()
    return (
        f"\n\nTODAY'S DATE is {today.isoformat()} ({today:%A, %d %B %Y}). "
        "Resolve EVERY relative date against this: today/bugün=today, "
        "tomorrow/yarın=+1 day, next week/haftaya=+7 days, "
        "next month/gelecek ay=+1 month, in N days/N gün sonra=+N days, "
        "this weekend/bu hafta sonu=the coming Saturday. NEVER pass a past "
        "date to a tool. Today is allowed when the user explicitly asks for "
        "today/bugün. If the user gives no date, choose a sensible near-future "
        "date about two weeks out."
    )


def _today_local() -> date:
    return date.today()


def _coerce_search_date(value: Any, *, default_days: int) -> str:
    """Return a valid non-past ``YYYY-MM-DD`` string.

    Missing, malformed or past dates fall back to ``today + default_days``.
    Today's date is accepted so "today/bugün" can be searched directly.
    """
    today = _today_local()
    fallback = (today + timedelta(days=default_days)).isoformat()
    if not isinstance(value, str):
        return fallback
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        return fallback
    if parsed < today:
        return fallback
    return parsed.isoformat()


_MONTHS = {
    "january": 1,
    "jan": 1,
    "ocak": 1,
    "february": 2,
    "feb": 2,
    "subat": 2,
    "şubat": 2,
    "march": 3,
    "mar": 3,
    "mart": 3,
    "april": 4,
    "apr": 4,
    "nisan": 4,
    "may": 5,
    "mayis": 5,
    "mayıs": 5,
    "june": 6,
    "jun": 6,
    "haziran": 6,
    "july": 7,
    "jul": 7,
    "temmuz": 7,
    "august": 8,
    "aug": 8,
    "agustos": 8,
    "ağustos": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "eylul": 9,
    "eylül": 9,
    "october": 10,
    "oct": 10,
    "ekim": 10,
    "november": 11,
    "nov": 11,
    "kasim": 11,
    "kasım": 11,
    "december": 12,
    "dec": 12,
    "aralik": 12,
    "aralık": 12,
}

_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_IN_DAYS_RE = re.compile(r"\bin\s+(\d{1,3})\s+days?\b", re.IGNORECASE)
_TR_IN_DAYS_RE = re.compile(r"\b(\d{1,3})\s+g[uü]n\s+sonra\b", re.IGNORECASE)
_DAY_MONTH_YEAR_RE = re.compile(
    r"\b(\d{1,2})\s+([A-Za-zÀ-ž]+)\s*(20\d{2})?\b",
    re.IGNORECASE,
)


def _normalize_date_text(text: str) -> str:
    lowered = text.casefold()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _resolve_explicit_date_from_text(text: str, *, today: date | None = None) -> date | None:
    """Resolve one explicit/relative travel date from free text."""
    anchor = today or _today_local()
    normalized = _normalize_date_text(text)

    if match := _ISO_DATE_RE.search(normalized):
        return _safe_date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
    if re.search(r"\b(today|bugun)\b", normalized):
        return anchor
    if re.search(r"\b(tomorrow|yarin)\b", normalized):
        return anchor + timedelta(days=1)
    if re.search(r"\b(next week|haftaya|gelecek hafta)\b", normalized):
        return anchor + timedelta(days=7)
    if re.search(r"\b(this weekend|bu hafta sonu)\b", normalized):
        days_until_saturday = (5 - anchor.weekday()) % 7
        return anchor + timedelta(days=days_until_saturday)
    if match := _IN_DAYS_RE.search(normalized):
        return anchor + timedelta(days=int(match.group(1)))
    if match := _TR_IN_DAYS_RE.search(normalized):
        return anchor + timedelta(days=int(match.group(1)))
    if match := _DAY_MONTH_YEAR_RE.search(normalized):
        day = int(match.group(1))
        month = _MONTHS.get(match.group(2).strip(". ").casefold())
        if month is None:
            return None
        if match.group(3):
            return _safe_date(int(match.group(3)), month, day)
        parsed = _safe_date(anchor.year, month, day)
        if parsed is None:
            return None
        if parsed < anchor:
            return _safe_date(anchor.year + 1, month, day)
        return parsed
    return None


class AgentNotConfiguredError(Exception):
    """Raised when no OpenAI key is configured."""


# ── Result ordering ──────────────────────────────────────────────────────────
#
# The providers (Google Flights / Hotels) return options in a relevance order,
# not by price/quality. But the assistant's text reply names ONE best pick while
# the UI only renders the first card(s) — so a named option that sat lower in the
# list was invisible. We make ordering explicit and intent-driven: the model maps
# the user's words ("cheapest", "en ucuz", "fastest", "luxury", "best rated") to
# a `sort` key, the backend applies it deterministically, and the cards render in
# that same order. Result: the option the model recommends is always the first
# card, for EVERY phrasing the user can throw at it.


def _num(value: Any) -> float | None:
    # bool is an int subclass — exclude it so True/False never sort as 1/0.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _order_options(
    options: list[dict[str, Any]],
    value_fn: Any,
    *,
    reverse: bool = False,
) -> list[dict[str, Any]]:
    """Stable sort that always sinks options with a missing value to the end,
    regardless of direction — so "cheapest/fastest first" never surfaces a
    priceless/unknown row above real ones, and "most expensive" doesn't either.
    """
    present = [o for o in options if value_fn(o) is not None]
    missing = [o for o in options if value_fn(o) is None]
    present.sort(key=value_fn, reverse=reverse)
    return present + missing


def _hotel_total_price(o: dict[str, Any]) -> float | None:
    total = _num(o.get("price"))
    if total is not None:
        return total
    per_night = _num(o.get("perNight"))
    if per_night is not None:
        return per_night * (o.get("nights") or 1)
    return None


# Map a sort key → an ordering function. The key set is mirrored in each tool's
# JSON schema enum, so the model can only ever pass a key we implement.
_HOTEL_SORTS: dict[str, Any] = {
    "price_asc": lambda o: _order_options(o, _hotel_total_price),
    "price_desc": lambda o: _order_options(o, _hotel_total_price, reverse=True),
    "rating_desc": lambda o: _order_options(
        o, lambda x: _num(x.get("rating")), reverse=True
    ),
    "stars_desc": lambda o: _order_options(
        o, lambda x: _num(x.get("stars")), reverse=True
    ),
}

_FLIGHT_SORTS: dict[str, Any] = {
    "price_asc": lambda o: _order_options(o, lambda x: _num(x.get("price"))),
    "price_desc": lambda o: _order_options(
        o, lambda x: _num(x.get("price")), reverse=True
    ),
    "duration_asc": lambda o: _order_options(
        o, lambda x: _num(x.get("durationMinutes"))
    ),
    "stops_asc": lambda o: _order_options(o, lambda x: _num(x.get("stops"))),
    "depart_asc": lambda o: _order_options(o, lambda x: x.get("departureTime") or None),
    "depart_desc": lambda o: _order_options(
        o, lambda x: x.get("departureTime") or None, reverse=True
    ),
}


def _apply_sort(
    options: list[dict[str, Any]],
    sorts: dict[str, Any],
    requested: Any,
    *,
    default: str,
) -> tuple[list[dict[str, Any]], str]:
    """Order ``options`` by the requested sort key, falling back to ``default``.
    Returns the ordered list and the sort key actually applied (echoed to the
    model so its prose and the cards agree on what 'first' means)."""
    key = (requested or "").strip() if isinstance(requested, str) else ""
    fn = sorts.get(key)
    if fn is None:
        key = default
        fn = sorts[default]
    return fn(options), key


# Human-readable labels for the enum-like preference fields.
_CABIN_LABELS = {
    "economy": "economy",
    "premium_economy": "premium economy",
    "business": "business",
    "first": "first class",
}
_HOTEL_TIER_LABELS = {
    "budget": "budget",
    "standard": "standard",
    "luxury": "luxury",
}
_SEAT_LABELS = {
    "window": "window",
    "aisle": "aisle",
    "no_preference": "no seat preference",
}

_CITY_ALIASES = {
    "ankara": "ESB",
    "ankara esenboga": "ESB",
    "ankara esenboga airport": "ESB",
    "ankara esenboğa": "ESB",
    "ankara esenboğa airport": "ESB",
    "istanbul": "IST",
    "istanbul airport": "IST",
    "istanbul havalimani": "IST",
    "istanbul havalimanı": "IST",
    "izmir": "ADB",
    "roma": "FCO",
    "londra": "LHR",
    "paris": "CDG",
}



_TR_CHARS = set("çğıöşüÇĞİÖŞÜ")
# Whole-word Turkish cues. Matched as full words (not substrings) so English
# like "hotel" / "Istanbul" doesn't trip "otel" / "bul".
_TR_HINT_WORDS = {
    "ve",
    "bir",
    "otel",
    "uçuş",
    "için",
    "bul",
    "rezervasyon",
    "bütçe",
    "yarın",
    "haftaya",
    "merhaba",
    "lütfen",
    "nasıl",
    "göster",
    "kaldı",
}
_WORD_RE = re.compile(r"[a-zçğıöşü]+")


def _looks_turkish(text: str) -> bool:
    """Best-effort language guess so the hand-written fallback line matches the
    user's language (the model itself is already told to mirror it)."""
    if any(ch in _TR_CHARS for ch in text):
        return True
    return bool(set(_WORD_RE.findall(text.casefold())) & _TR_HINT_WORDS)


_CONFIRMATION_RE = re.compile(
    r"^(yes|yeah|yep|ok|okay|sure|confirm|do it|"
    r"evet|tamam|onayliyorum|onaylıyorum)$",
    re.IGNORECASE,
)

_FOLLOW_UP_RE = re.compile(
    r"\b(first|second|third|cheaper|cheapest|faster|earlier|later|same|that|this|"
    r"ilk|ikinci|ucuncu|üçüncü|ucuz|en ucuz|daha ucuz|hizli|hızlı|erken|gec|geç|"
    r"ayni|aynı|bunu|sunu|şunu|onu)\b",
    re.IGNORECASE,
)

_ACTION_RE = re.compile(
    r"\b(find|search|show|book|reserve|plan|compare|check|buy|"
    r"bul|ara|goster|göster|rezerve|planla|karsilastir|karşılaştır|"
    r"kontrol|satin al|satın al)\b",
    re.IGNORECASE,
)

_DATE_FOLLOW_UP_RE = re.compile(
    r"(\b\d{1,2}\s*[-/]\s*\d{1,2}\b|"
    r"\b\d{1,2}\s+([a-zçğıöşü]+)\b|"
    r"\b(today|tomorrow|next week|next month|this weekend)\b|"
    r"\b(bugun|bugün|yarin|yarın|haftaya|gelecek hafta|gelecek ay|bu hafta sonu)\b)",
    re.IGNORECASE,
)

_TRAVEL_ENTITY_RE = re.compile(
    r"\b(flight|hotel|restaurant|reservation|booking|trip|budget|wallet|car|transfer|"
    r"ucus|uçuş|otel|restoran|rezervasyon|seyahat|butce|bütçe|cuzdan|cüzdan|"
    r"arac|araç|transfer)\b",
    re.IGNORECASE,
)


def _looks_like_incomplete_voice_input(text: str) -> bool:
    normalized = _normalize_date_text(text).strip()
    normalized = re.sub(r"\s+", " ", normalized)

    if not normalized:
        return True

    words = normalized.split()

    if len(words) == 1:
        return True

    if len(words) <= 2 and not (
        _ACTION_RE.search(normalized) or _TRAVEL_ENTITY_RE.search(normalized)
    ):
        return True

    return False


def _looks_like_follow_up(text: str) -> bool:
    normalized = _normalize_date_text(text)
    return bool(
        _FOLLOW_UP_RE.search(normalized)
        or _CONFIRMATION_RE.search(normalized)
        or _DATE_FOLLOW_UP_RE.search(normalized)
    )

def _has_recent_assistant_context(history: list[dict[str, str]]) -> bool:
    for message in reversed(history[-4:]):
        if message.get("role") == "assistant" and message.get("content", "").strip():
            return True
    return False

_NEAR_LOCATION_PATTERNS = [
    re.compile(
        r"(.+?)\s*(?:'?[ea]?\s*)?(?:yak[iı]n|civar[iı]nda|etraf[iı]nda)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:near|close to|around|nearby)\s+(.+?)(?:\s+(?:hotel|hotels|restaurant|restaurants|otel|restoran))?$",
        re.IGNORECASE,
    ),
]


def _extract_near_location(text: str) -> str | None:
    cleaned = text.strip(" .,!?:;")

    for pattern in _NEAR_LOCATION_PATTERNS:
        match = pattern.search(cleaned)
        if not match:
            continue

        place = match.group(1).strip(" .,!?:;'’")

        place = re.sub(
            r"\b(hotel|hotels|restaurant|restaurants|otel|restoran|bul|ara|goster|göster)\b",
            "",
            place,
            flags=re.IGNORECASE,
        ).strip(" .,!?:;'’")

        if len(place) >= 3:
            return place

    return None

_FROM_TO_ROUTE_RE = re.compile(
    r"\bfrom\s+([A-Za-zÀ-ž .'-]+?)\s+to\s+([A-Za-zÀ-ž .'-]+?)(?:\b|$)",
    re.IGNORECASE,
)

_TR_ARASI_ROUTE_RE = re.compile(
    r"\b([A-Za-zÀ-ž .'-]+?)\s+([A-Za-zÀ-ž .'-]+?)\s+arası\b",
    re.IGNORECASE,
)

def _build_preferences_block(preferences: dict | None) -> str:
    """Render a concise traveller-profile block for the system prompt.

    Returns an empty string when there are no usable preferences, so the
    system prompt is unchanged for users without a saved profile. The block is
    phrased as *soft defaults* the user can always override.
    """

    if not preferences:
        return ""

    parts: list[str] = []
    home_airport = preferences.get("homeAirport")
    home_city = preferences.get("homeCity")
    if home_airport:
        parts.append(f"home airport {home_airport}")
    if home_city:
        parts.append(f"based in {home_city}")
    cabin = preferences.get("preferredCabin")
    if cabin:
        parts.append(f"prefers {_CABIN_LABELS.get(cabin, cabin)} cabin")
    hotel_tier = preferences.get("hotelTier")
    if hotel_tier:
        parts.append(f"{_HOTEL_TIER_LABELS.get(hotel_tier, hotel_tier)} hotels")
    seat = preferences.get("seatPreference")
    if seat and seat != "no_preference":
        parts.append(f"{_SEAT_LABELS.get(seat, seat)} seat")
    dietary = preferences.get("dietary") or []
    if dietary:
        parts.append(f"dietary: {', '.join(dietary)}")
    interests = preferences.get("interests") or []
    if interests:
        parts.append(f"interests: {', '.join(interests)}")
    currency = preferences.get("currency")
    if currency:
        parts.append(f"prefers prices in {currency}")
    language = preferences.get("language")
    if language:
        parts.append(f"replies in language '{language}' when ambiguous")
    notes = preferences.get("notes")
    if notes:
        parts.append(f"notes: {notes}")

    if not parts:
        return ""

    return (
        " Traveller profile (use ONLY as sensible defaults; the user's explicit "
        "request always wins): " + "; ".join(parts) + ". "
        "Apply these softly — e.g. default the flight origin to their home "
        "airport when none is given, bias hotel searches toward their tier, and "
        "respect dietary needs in restaurant picks — but never override what the "
        "user actually asks for, and still rely on the rule about replying in "
        "the user's written language."
    )


_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": "Search live flight options between two airports.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "3-letter IATA origin, e.g. IST"},
                    "destination": {"type": "string", "description": "3-letter IATA destination, e.g. FCO"},
                    "outbound_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "return_date": {"type": "string", "description": "YYYY-MM-DD, optional for round trips"},
                    "adults": {"type": "integer", "minimum": 1, "default": 1},
                    "sort": {
                        "type": "string",
                        "enum": [
                            "price_asc",
                            "price_desc",
                            "duration_asc",
                            "stops_asc",
                            "depart_asc",
                            "depart_desc",
                        ],
                        "description": (
                            "Order results by the user's intent: price_asc=cheapest, "
                            "price_desc=most expensive, duration_asc=fastest, "
                            "stops_asc=fewest stops/direct, depart_asc=earliest "
                            "departure, depart_desc=latest. Defaults to price_asc."
                        ),
                    },
                },
                "required": ["origin", "destination", "outbound_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_budget",
            "description": "Get the remaining demo travel budget.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_flight",
            "description": (
                "Book (simulate buying) a flight the user has CONFIRMED, deducting "
                "the budget. Use values from a prior search_flights result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "airline": {"type": "string"},
                    "origin": {"type": "string"},
                    "destination": {"type": "string"},
                    "date": {"type": "string", "description": "Outbound date / time"},
                    "price": {"type": "number", "description": "Price in the currency below"},
                    "currency": {"type": "string", "default": "USD"},
                },
                "required": ["airline", "origin", "destination", "price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hotels",
            "description": "Search live hotel options in a city for a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City, e.g. Rome"},
                    "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                    "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                    "adults": {"type": "integer", "minimum": 1, "default": 2},
                    "sort": {
                        "type": "string",
                        "enum": [
                            "price_asc",
                            "price_desc",
                            "rating_desc",
                            "stars_desc",
                        ],
                        "description": (
                            "Order results by the user's intent: price_asc=cheapest/"
                            "most affordable, price_desc=most expensive, "
                            "rating_desc=best guest rating, stars_desc=most stars/"
                            "most luxurious. Defaults to price_asc."
                        ),
                    },
                },
                "required": ["location", "check_in", "check_out"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_hotel",
            "description": (
                "Book a CONFIRMED hotel for the stay, deducting the budget. Use "
                "values from a prior search_hotels result (price = stay total)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "location": {"type": "string"},
                    "check_in": {"type": "string"},
                    "check_out": {"type": "string"},
                    "price": {"type": "number"},
                    "currency": {"type": "string", "default": "USD"},
                },
                "required": ["name", "price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_restaurants",
            "description": "Search restaurants (e.g. 'Italian restaurants') in a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "e.g. 'Italian restaurants'"},
                    "location": {"type": "string", "description": "City, e.g. Rome"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_restaurant",
            "description": (
                "Reserve a CONFIRMED restaurant (free). Use values from a prior "
                "search_restaurants result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "location": {"type": "string"},
                    "datetime": {"type": "string", "description": "When, e.g. 'Sat 20:00'"},
                },
                "required": ["name"],
            },
        },
    },
]


class AgentService:
    def __init__(
        self,
        *,
        settings: Settings,
        flights: FlightService,
        hotels: HotelSearchService,
        restaurants: RestaurantService,
        wallet: WalletService,
        guest_id: str,
        preferences: dict | None = None,
    ) -> None:
        self._settings = settings
        self._flights = flights
        self._hotels = hotels
        self._restaurants = restaurants
        self._wallet = wallet
        self._guest_id = guest_id
        # Habit-aware soft defaults for the system prompt (empty if unset).
        self._system_prompt = (
            _SYSTEM_PROMPT + _today_context() + _build_preferences_block(preferences)
        )
        self._latest_user_text = ""
        # Artifacts collected during the turn for the UI.
        self.flight_options: list[dict[str, Any]] = []
        self.hotel_options: list[dict[str, Any]] = []
        self.restaurant_options: list[dict[str, Any]] = []
        self.booked: dict[str, Any] | None = None

    def _sanitize_history(
        self,
        history: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Keep only recent, valid user/assistant turns before sending to the LLM.

        The mobile client sends the full conversation history because the server is
        stateless. This guard prevents stale, empty, invalid, or oversized context
        from confusing the assistant.
        """
        cleaned: list[dict[str, str]] = []

        for message in history[-10:]:
            role = message.get("role")
            content = (message.get("content") or "").strip()

            if role not in {"user", "assistant"}:
                continue
            if not content:
                continue

            # Avoid sending very large accidental payloads to the model.
            if len(content) > 2000:
                content = content[:2000].strip()

            cleaned.append({"role": role, "content": content})

        return cleaned

    async def run(self, history: list[dict[str, str]]) -> str:
        if not self._settings.openai_api_key:
            raise AgentNotConfiguredError()

        clean_history = self._sanitize_history(history)

        self._latest_user_text = next(
            (
                m.get("content", "")
                for m in reversed(clean_history)
                if m.get("role") == "user"
            ),
            "",
        )

        has_context = _has_recent_assistant_context(clean_history)

        if (
            _looks_like_incomplete_voice_input(self._latest_user_text)
            and not (_looks_like_follow_up(self._latest_user_text) and has_context)
        ):
            if _looks_turkish(self._latest_user_text):
                return (
                    "Biraz daha açar mısın? Uçuş, otel, restoran ya da bütçe "
                    "için ne yapmamı istersin?"
                )
            return (
                "Could you clarify that a bit? Do you want flights, hotels, "
                "restaurants, or budget help?"
            )
        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            *clean_history,
        ]

        for _ in range(6):  # bounded tool-calling loop
            resp = await client.chat.completions.create(
                model=self._settings.openai_model,
                messages=messages,
                tools=_TOOLS,
                temperature=0.1,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                fallback = await self._fallback_flight_search(clean_history)
                if fallback is not None:
                    return fallback
                return msg.content or ""

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                result = await self._dispatch(
                    tc.function.name, tc.function.arguments
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    }
                )

        return (
            "I wasn't able to finish that in time — could you rephrase or narrow it "
            "down?"
        )

    async def _dispatch(self, name: str, raw_args: str) -> dict[str, Any]:
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            return {"error": "bad arguments"}

        if name == "search_flights":
            return await self._tool_search_flights(args)
        if name == "get_budget":
            return await self._tool_get_budget()
        if name == "book_flight":
            return await self._tool_book_flight(args)
        if name == "search_hotels":
            return await self._tool_search_hotels(args)
        if name == "book_hotel":
            return await self._tool_book_hotel(args)
        if name == "search_restaurants":
            return await self._tool_search_restaurants(args)
        if name == "book_restaurant":
            return await self._tool_book_restaurant(args)
        return {"error": f"unknown tool {name}"}

    async def _tool_search_flights(self, args: dict) -> dict[str, Any]:
        # Voice requests often mention dates naturally ("today", "5 gün sonra",
        # "26 eylül"), and the model may omit or mangle them. Resolve the most
        # recent user text first, then validate whatever tool args remain.
        hinted_outbound = _resolve_explicit_date_from_text(self._latest_user_text)
        outbound_date = (
            hinted_outbound.isoformat()
            if hinted_outbound is not None
            else _coerce_search_date(args.get("outbound_date"), default_days=14)
        )
        return_date = args.get("return_date")
        if return_date:
            return_date = _coerce_search_date(return_date, default_days=21)
            # A round trip's return must be after departure.
            if date.fromisoformat(return_date) <= date.fromisoformat(outbound_date):
                return_date = (
                    date.fromisoformat(outbound_date) + timedelta(days=7)
                ).isoformat()
        origin = self._resolve_airport_code(args.get("origin"))
        destination = self._resolve_airport_code(args.get("destination"))
        if origin is None or destination is None:
            return {
                "error": "unknown origin/destination",
                "origin": args.get("origin"),
                "destination": args.get("destination"),
            }
        try:
            options = await self._flights.search(
                origin=origin,
                destination=destination,
                outbound_date=outbound_date,
                return_date=return_date,
                adults=int(args.get("adults", 1)),
            )
        except (FlightSearchError, KeyError) as exc:
            return {"error": f"search failed: {exc}"}
        # Order by the user's intent (cheapest/fastest/fewest stops/earliest…) so
        # the option the model recommends is the same one shown as the first card.
        options, applied_sort = _apply_sort(
            options, _FLIGHT_SORTS, args.get("sort"), default="price_asc"
        )
        self.flight_options = options[:6]
        # Trim for the model (token budget): top 5 with the essentials.
        slim = [
            {
                "airline": o["airline"],
                "price": o["price"],
                "currency": o["currency"],
                "from": o["departureAirport"],
                "to": o["arrivalAirport"],
                "depart": o["departureTime"],
                "arrive": o["arrivalTime"],
                "stops": o["stops"],
            }
            for o in self.flight_options[:5]
        ]
        return {
            "options": slim,
            "count": len(slim),
            "resolvedOrigin": origin,
            "resolvedDestination": destination,
            "resolvedOutboundDate": outbound_date,
            "sortedBy": applied_sort,
        }

    async def _tool_get_budget(self) -> dict[str, Any]:
        budget = await self._wallet.ensure_budget(self._guest_id)
        return {"balance": budget.balance_cents / 100, "currency": budget.currency}

    async def _tool_book_flight(self, args: dict) -> dict[str, Any]:
        try:
            price = float(args["price"])
            origin = args["origin"]
            destination = args["destination"]
            airline = args["airline"]
        except (KeyError, ValueError, TypeError):
            return {"error": "missing/invalid booking fields"}

        currency = args.get("currency") or self._settings.demo_budget_currency
        date = args.get("date", "")
        try:
            purchase, budget = await self._wallet.purchase(
                guest_id=self._guest_id,
                kind="flight",
                title=f"{origin} → {destination}",
                subtitle=f"{airline}{f' · {date}' if date else ''}",
                amount_cents=round(price * 100),
                currency=currency,
                details={
                    "airline": airline,
                    "origin": origin,
                    "destination": destination,
                    "date": date,
                },
            )
        except InsufficientBudgetError as exc:
            return {
                "error": "insufficient_budget",
                "balance": exc.balance_cents / 100,
            }
        except InvalidPurchaseError:
            return {"error": "invalid purchase"}

        self._record_booked(purchase)
        return {
            "booked": True,
            "title": purchase.title,
            "price": price,
            "currency": currency,
            "remaining_budget": budget.balance_cents / 100,
        }

    async def _tool_search_hotels(self, args: dict) -> dict[str, Any]:
        location = str(args.get("location") or "").strip()

        near_location = _extract_near_location(self._latest_user_text)
        if near_location:
            if location:
                location = f"{near_location}, {location}"
            else:
                location = near_location

        if not location:
            return {"error": "missing location"}
        
        # Same date defence as flights: a missing/past/invalid stay window
        # would otherwise make the provider fail outright.
        hinted_check_in = _resolve_explicit_date_from_text(self._latest_user_text)
        check_in = (
            hinted_check_in.isoformat()
            if hinted_check_in is not None
            else _coerce_search_date(args.get("check_in"), default_days=14)
        )
        check_out = _coerce_search_date(args.get("check_out"), default_days=17)
        if date.fromisoformat(check_out) <= date.fromisoformat(check_in):
            check_out = (date.fromisoformat(check_in) + timedelta(days=3)).isoformat()
        try:
            options = await self._hotels.search(
                location=location,
                check_in=check_in,
                check_out=check_out,
                adults=int(args.get("adults", 2)),
            )
        except (HotelSearchError, KeyError) as exc:
            return {"error": f"search failed: {exc}"}
        # Order by the user's intent (cheapest/luxury/best-rated…). The cards the
        # UI shows follow this same order, so the option the model names as the
        # best match is always the first card.
        options, applied_sort = _apply_sort(
            options, _HOTEL_SORTS, args.get("sort"), default="price_asc"
        )
        self.hotel_options = options[:6]
        slim = [
            {
                "name": o["name"],
                "price": o["price"],
                "perNight": o["perNight"],
                "nights": o["nights"],
                "currency": o["currency"],
                "rating": o["rating"],
                "stars": o["stars"],
            }
            for o in self.hotel_options[:5]
        ]
        return {"options": slim, "count": len(slim), "sortedBy": applied_sort}

    async def _tool_book_hotel(self, args: dict) -> dict[str, Any]:
        try:
            price = float(args["price"])
            name = args["name"]
        except (KeyError, ValueError, TypeError):
            return {"error": "missing/invalid booking fields"}
        currency = args.get("currency") or self._settings.demo_budget_currency
        location = args.get("location", "")
        check_in = args.get("check_in", "")
        check_out = args.get("check_out", "")
        window = f"{check_in}–{check_out}".strip("–")
        try:
            purchase, budget = await self._wallet.purchase(
                guest_id=self._guest_id,
                kind="hotel",
                title=name,
                subtitle=f"{location}{f' · {window}' if window else ''}".strip(),
                amount_cents=round(price * 100),
                currency=currency,
                details={"location": location, "checkIn": check_in, "checkOut": check_out},
            )
        except InsufficientBudgetError as exc:
            return {"error": "insufficient_budget", "balance": exc.balance_cents / 100}
        except InvalidPurchaseError:
            return {"error": "invalid purchase"}
        self._record_booked(purchase)
        return {
            "booked": True,
            "title": purchase.title,
            "price": price,
            "currency": currency,
            "remaining_budget": budget.balance_cents / 100,
        }

    async def _tool_search_restaurants(self, args: dict) -> dict[str, Any]:
        try:
            location = args.get("location")
            near_location = _extract_near_location(self._latest_user_text)

            if near_location:
                location = f"{near_location}, {location}" if location else near_location

            options = await self._restaurants.search(
                query=args["query"],
                location=location,
            )
        except (RestaurantSearchError, KeyError) as exc:
            return {"error": f"search failed: {exc}"}
        self.restaurant_options = options[:6]
        slim = [
            {
                "name": o["name"],
                "rating": o["rating"],
                "priceLevel": o["priceLevel"],
                "type": o["type"],
                "address": o["address"],
            }
            for o in self.restaurant_options[:5]
        ]
        return {"options": slim, "count": len(slim)}

    async def _tool_book_restaurant(self, args: dict) -> dict[str, Any]:
        try:
            name = args["name"]
        except KeyError:
            return {"error": "missing name"}
        location = args.get("location", "")
        when = args.get("datetime", "")
        try:
            purchase, _ = await self._wallet.purchase(
                guest_id=self._guest_id,
                kind="restaurant",
                title=name,
                subtitle=f"{location}{f' · {when}' if when else ''}".strip(" ·"),
                amount_cents=0,
                currency=self._settings.demo_budget_currency,
                details={"location": location, "when": when},
            )
        except InvalidPurchaseError:
            return {"error": "invalid purchase"}
        self._record_booked(purchase)
        return {"reserved": True, "name": name, "when": when}

    def _record_booked(self, purchase: Any) -> None:
        self.booked = {
            "id": purchase.id,
            "kind": purchase.kind,
            "title": purchase.title,
            "subtitle": purchase.subtitle,
            "amountCents": purchase.amount_cents,
            "currency": purchase.currency,
        }

    async def _fallback_flight_search(
        self, history: list[dict[str, str]]
    ) -> str | None:
        last_user = next(
            (m.get("content", "") for m in reversed(history) if m.get("role") == "user"),
            "",
        ).strip()
        if not last_user:
            return None
        route = self._extract_route(last_user)
        if route is None:
            return None
        origin, destination = route
        result = await self._tool_search_flights(
            {
                "origin": origin,
                "destination": destination,
            }
        )
        if result.get("error") is not None:
            return None
        count = int(result.get("count") or 0)
        if count == 0:
            return None
        origin_code = result["resolvedOrigin"]
        dest_code = result["resolvedDestination"]
        if _looks_turkish(last_user):
            return (
                f"{origin_code} → {dest_code} için {count} uçuş seçeneği buldum — "
                "kartlardan birine dokunarak devam edebilirsin."
            )
        plural = "s" if count != 1 else ""
        return (
            f"I found {count} flight option{plural} for {origin_code} → {dest_code} "
            "— tap a card to continue."
        )

    def _resolve_airport_code(self, raw: Any) -> str | None:
        if not isinstance(raw, str):
            return None
        value = raw.strip()
        if not value:
            return None
        if len(value) == 3 and value.isalpha():
            return value.upper()

        key = self._normalize_place_key(value)
        if key in _CITY_ALIASES:
            return _CITY_ALIASES[key]
        if key in CITY_TO_IATA:
            return CITY_TO_IATA[key]
        return None

    def _normalize_place_key(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold())
        ascii_only = "".join(
            ch for ch in normalized if not unicodedata.combining(ch)
        )
        return " ".join(ascii_only.replace("-", " ").split())

    def _extract_route(self, text: str) -> tuple[str, str] | None:
        if m := _FROM_TO_ROUTE_RE.search(text):
            return m.group(1).strip(), m.group(2).strip()
        if m := _TR_ARASI_ROUTE_RE.search(text):
            return m.group(1).strip(), m.group(2).strip()
        return None
