"""Lightweight goal parsing used by the demo planner (and as hints for the LLM planner)."""

from __future__ import annotations

import re

from ..platforms import ORDER

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "fourteen": 14}
CATEGORIES = ["sofa", "sectional", "bed", "dining table", "coffee table", "accent chair", "chair", "wardrobe",
              "bookshelf", "table",
              # devotional / pooja retail
              "diya", "deepa", "lamp", "brass", "kalash", "kalasa", "idol", "agarbatti", "incense", "camphor", "kumkum",
              "haldi", "chandan", "pooja essentials", "ayurvedic", "copper", "german silver"]
OCCASIONS = {"diwali": "Deepavali", "deepavali": "Deepavali", "dussehra": "Dussehra", "navratri": "Navaratri",
             "navaratri": "Navaratri", "onam": "Onam", "christmas": "Christmas", "new year": "New Year",
             "wedding": "Wedding season", "republic day": "Republic Day", "independence day": "Independence Day",
             "pongal": "Sankranti", "sankranti": "Sankranti", "monsoon": "Monsoon", "karthika": "Karthika",
             "kartika": "Karthika", "tulsi vivah": "Tulsi Vivah", "ganesh chaturthi": "Ganesh Chaturthi",
             "ganesha": "Ganesh Chaturthi", "janmashtami": "Krishna Janmashtami", "ugadi": "Ugadi",
             "varamahalakshmi": "Varamahalakshmi"}
CITIES = ["bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "chennai", "pune", "kolkata", "gurugram", "noida",
          "mysuru", "mysore"]
PLATFORM_WORDS = {"instagram": "instagram", "insta": "instagram", "facebook": "facebook", "fb": "facebook",
                  "pinterest": "pinterest", "twitter": "x", "linkedin": "linkedin", "youtube": "youtube",
                  "threads": "threads"}


def _platforms(g: str) -> list[str]:
    if re.search(r"\b(all|every|seven|7)\s+(?:social\s+)?(platforms|channels|networks)\b", g):
        return list(ORDER)
    found = []
    for word, key in PLATFORM_WORDS.items():
        if re.search(rf"\b{word}\b", g) and key not in found:
            found.append(key)
    if re.search(r"\bon x\b|\bx \(twitter\)|\band x\b|, x\b", g) and "x" not in found:
        found.append("x")
    return sorted(found, key=ORDER.index)


def parse_goal(goal: str) -> tuple[str, dict]:
    g = goal.lower()
    if re.search(r"\b(evaluate|results|performance|what worked|what to change|how did|learn)", g):
        intent = "evaluate"
    elif re.search(r"\breport\b", g) and not re.search(r"\b(campaign|calendar|plan)\b.*\b(create|plan|build)", g):
        intent = "report"
    elif re.search(r"\bcompetitor|competition|rival", g) and not re.search(r"\b(create|plan|campaign)\b", g):
        intent = "competitor"
    elif re.search(r"\b(research|trend|opportunit|insight)", g) and not re.search(r"\b(create|plan|campaign|calendar)\b", g):
        intent = "research"
    else:
        intent = "campaign"
    days = 7
    m = re.search(r"(\d{1,2})[\s-]*(?:day|days)\b", g)
    if m:
        days = int(m.group(1))
    else:
        m = re.search(r"\b(" + "|".join(NUMBER_WORDS) + r")[\s-]*day", g)
        if m:
            days = NUMBER_WORDS[m.group(1)]
        elif "next week" in g or "weekly" in g:
            days = 7
        elif "fortnight" in g or "two weeks" in g:
            days = 14
        elif re.search(r"\b(?:single|one|1)\b[\w\s-]{0,100}\bposts?\b", g):
            # A request for one post should not silently expand to the default week.
            days = 1
    platforms = _platforms(g)
    option_count = 1
    explicit_option = re.search(
        r"\b(?P<count>\d+|one|two|three|four|five)\b"
        r"(?:\s+(?:different|selectable|alternative|distinct|separate|post|image|caption|content|creative|and)){0,5}"
        r"\s+options?\b", g)
    if explicit_option:
        raw_count = explicit_option.group("count")
        option_count = int(raw_count) if raw_count.isdigit() else NUMBER_WORDS[raw_count]
    elif re.search(r"\b(?:multiple|several)\b(?:\s+[\w-]+){0,3}\s+options?\b|\boptions?\s+to\s+choose\b", g):
        option_count = 3
    params = {
        "days": max(1, min(days, 14)),
        "platform": platforms[0] if platforms else "instagram",
        "platforms": platforms,
        "category": next((c for c in CATEGORIES if re.search(rf"\b{re.escape(c)}s?\b", g)), None),
        "occasion": next((name for word, name in OCCASIONS.items() if word in g), None),
        "geography": next((("Bengaluru" if c in ("bengaluru", "bangalore") else "Mysuru" if c in ("mysuru", "mysore")
                            else c.title()) for c in CITIES if c in g), None),
        "ai_background": bool(re.search(r"\b(?:gemini|ai[- ]generated background|ai background)\b", g)),
        "content_type": "post" if re.search(r"\b(?:static(?:\s+image)?|single[- ]image|not\s+(?:a\s+)?carousel|no\s+carousel)\b", g) else None,
        "option_count": max(1, min(option_count, 5)),
    }
    return intent, params
