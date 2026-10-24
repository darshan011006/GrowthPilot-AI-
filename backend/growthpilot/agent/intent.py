"""Lightweight goal parsing used by the demo planner (and as hints for the LLM planner)."""

from __future__ import annotations

import re

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "fourteen": 14}
CATEGORIES = ["sofa", "sectional", "bed", "dining table", "coffee table", "accent chair", "chair", "wardrobe",
              "bookshelf", "table"]
OCCASIONS = ["diwali", "dussehra", "navratri", "onam", "christmas", "new year", "wedding", "republic day",
             "independence day", "pongal", "sankranti", "monsoon"]
CITIES = ["bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "chennai", "pune", "kolkata", "gurugram", "noida"]
PLATFORMS = ["instagram", "pinterest", "facebook", "tiktok", "youtube"]


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
    params = {
        "days": max(1, min(days, 14)),
        "platform": next((p for p in PLATFORMS if p in g), "instagram"),
        "category": next((c for c in CATEGORIES if c in g), None),
        "occasion": next((o.title() for o in OCCASIONS if o in g), None),
        "geography": next((("Bengaluru" if c in ("bengaluru", "bangalore") else c.title()) for c in CITIES if c in g),
                          None),
    }
    return intent, params
