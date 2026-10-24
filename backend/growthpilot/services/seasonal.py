"""Built-in seasonal calendar for Indian home & furniture marketing.

Festival dates follow the lunar calendar and differ by region; treat these as planning hints and
confirm locally. Each entry is surfaced as a *source-reported* finding from this built-in calendar,
never as independently verified fact.
"""

from __future__ import annotations

from datetime import date

OCCASIONS = [
    {"name": "Republic Day sales", "start": date(2027, 1, 22), "end": date(2027, 1, 26), "kind": "retail",
     "note": "Common sale window around 26 January."},
    {"name": "Makar Sankranti / Pongal", "start": date(2027, 1, 14), "end": date(2027, 1, 15), "kind": "festival",
     "note": "Harvest festival; regional home-refresh traditions in South India."},
    {"name": "Onam", "start": date(2026, 8, 26), "end": date(2026, 8, 26), "kind": "festival",
     "note": "Thiruvonam date per common calendars; confirm locally."},
    {"name": "Independence Day sales", "start": date(2026, 8, 12), "end": date(2026, 8, 15), "kind": "retail",
     "note": "Retail sale window around 15 August."},
    {"name": "Dussehra / Navratri", "start": date(2026, 10, 11), "end": date(2026, 10, 20), "kind": "festival",
     "note": "Festive buying season begins; confirm regional dates."},
    {"name": "Diwali", "start": date(2026, 11, 8), "end": date(2026, 11, 8), "kind": "festival",
     "note": "Peak home-refresh and gifting season; buying typically starts 2–4 weeks before. Confirm the date."},
    {"name": "Wedding season", "start": date(2026, 11, 15), "end": date(2027, 2, 28), "kind": "season",
     "note": "Approximate window; new-home and furnishing purchases often rise. Inference, not data."},
    {"name": "Christmas & year-end", "start": date(2026, 12, 20), "end": date(2026, 12, 31), "kind": "retail",
     "note": "Year-end sales and hosting season."},
    {"name": "Bengaluru monsoon", "start": date(2027, 6, 1), "end": date(2027, 9, 30), "kind": "season",
     "note": "Indoor living and cosy-corner themes; humidity-friendly materials questions."},
]


def upcoming(today: date, within_days: int = 75) -> list[dict]:
    out = []
    for o in OCCASIONS:
        if o["end"] >= today and (o["start"] - today).days <= within_days:
            out.append({**o, "days_until": max(0, (o["start"] - today).days)})
    return sorted(out, key=lambda o: o["start"])
