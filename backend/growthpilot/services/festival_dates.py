"""Festival dates checked against official holiday lists.

The store's festival calendar (``brand.catalogue_source["festivals"]``) has no dates, and a catalogue sync replaces
it, so checked dates live here and are merged in when briefs are written. Only add a date with its source; never
estimate one. Lunar festivals vary by region and tradition: these follow the Karnataka lists where available.

Checked 2026-10-31.
"""

from __future__ import annotations

import re
from datetime import date

CHECKED = "2026-10-31"
CAG_KARNATAKA_2026 = ("Holidays in Central Government offices in Karnataka, 2026 (Annexures I and II), CAG of India: "
                      "https://cag.gov.in/uploads/media/Holiday-List-2026-069521fe6f358d0-89936988.pdf")
DOPT_2027 = ("DoPT O.M. F.No. 12/2/2023-JCA of 16 July 2026, holidays in Central Government offices in 2027, para 6 "
             "(as reproduced at https://www.staffnews.in/2026/07/list-of-holidays-2027-to-be-observed-in-central-"
             "government-offices.html)")

# key → occurrences. Navaratri is deliberately absent: the official lists give Navami/Vijayadashami
# (20 Oct 2026) but not the start of the nine nights.
VERIFIED: dict[str, list[dict]] = {
    "janmashtami": [
        {"start": date(2026, 9, 4), "end": date(2026, 9, 4), "source": CAG_KARNATAKA_2026,
         "note": "Janmashtami, restricted holiday (Annexure II)"},
    ],
    "deepavali": [
        {"start": date(2026, 11, 8), "end": date(2026, 11, 8), "source": CAG_KARNATAKA_2026,
         "note": "Diwali (Deepavali), gazetted holiday (Annexure I); Naraka Chaturdashi the same day, Govardhan "
                 "Puja 9 Nov (Annexure II)"},
        {"start": date(2027, 10, 29), "end": date(2027, 10, 29), "source": DOPT_2027,
         "note": "Diwali (Deepavali), Friday 29 October 2027"},
    ],
}
ALIASES = {"diwali": "deepavali", "deepavali": "deepavali", "janmashtami": "janmashtami",
           "janamashtami": "janmashtami", "navaratri": "navaratri", "navratri": "navaratri",
           "dussehra": "navaratri"}


def festival_key(name_or_slug: str) -> str:
    """Canonical key for a festival name or slug ("Krishna Janmashtami" → "janmashtami")."""
    for word in re.findall(r"[a-z]+", (name_or_slug or "").lower()):
        if word in ALIASES:
            return ALIASES[word]
    return re.sub(r"[^a-z]", "", (name_or_slug or "").lower())


def next_verified(name_or_slug: str, today: date) -> dict | None:
    """The next checked occurrence that hasn't ended yet, or None."""
    occ = [o for o in VERIFIED.get(festival_key(name_or_slug), []) if o["end"] >= today]
    return min(occ, key=lambda o: o["start"]) if occ else None
