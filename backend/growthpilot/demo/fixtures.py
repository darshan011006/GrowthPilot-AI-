"""Demo data: a FICTIONAL furniture brand and SYNTHETIC observations/metrics.

Nothing here describes a real business. Every row is flagged ``is_synthetic=True`` and the UI labels it.
Fixture research has no source URLs, because inventing URLs would fabricate provenance.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import audit
from ..adapters.base import ConnectionContext
from ..adapters.demo_instagram import DemoInstagramAdapter
from ..models import (
    AgentRun,
    Asset,
    Brand,
    Campaign,
    ChannelConnection,
    Competitor,
    CompetitorObservation,
    ConnectionStatus,
    ContentItem,
    ContentStatus,
    EvidenceClass,
    Experiment,
    Hypothesis,
    MetricSnapshot,
    Persona,
    Product,
    PublishAttempt,
    Recommendation,
    Report,
    ResearchFinding,
    utcnow,
)
from ..services.assets import make_placeholder, store
from ..services.content import add_revision

BRAND = dict(
    name="Aranya Living",
    description="Aranya Living (a fictional demo brand) designs made-to-order sofas, beds and tables for apartment "
                "living, built in a Bengaluru workshop and sold online and at one experience centre.",
    positioning="Considered, comfortable furniture sized for real city apartments.",
    voice="Warm, practical and quietly confident. Short sentences. No hype.",
    tone="Helpful, like a friend who knows interiors.",
    audience="Urban homeowners and long-term renters, 28–45, furnishing 2BHK and 3BHK apartments in Bengaluru.",
    location="Bengaluru, India",
    goals="Grow considered-purchase leads for the new Kabini sofa collection; build saves and shares, not just likes.",
    website="",
    colors=["#E9E3D8", "#2F3A2F", "#B5643C"],
    visual_guidelines="Natural daylight, warm neutrals, sage and terracotta accents, uncluttered rooms, real scale.",
    approved_claims=["Free delivery within Bengaluru city limits", "5-year frame warranty on Kabini sofas",
                     "Made to order in our Bengaluru workshop"],
    restricted_claims=["eco-friendly", "sustainable", "handcrafted"],
    prohibited_messaging=["cheapest in India", "lifetime warranty", "100% waterproof", "Vastu-certified"],
    constraints="No discounts unless listed as approved claims. No customer testimonials without written consent.",
    permitted_sources=[],
)

PRODUCTS = [
    dict(sku="KAB-3S", name="Kabini 3-Seater Sofa", category="sofa", collection="Kabini",
         description="A deep-seated three-seater with a low, clean profile and removable covers.",
         price=Decimal("78500"), dimensions="W 210 × D 92 × H 84 cm",
         materials=["solid acacia wood frame", "high-resilience foam", "linen-cotton blend upholstery"],
         finishes=["Sage", "Oat", "Terracotta"],
         verified_attributes={"warranty": "5 years on the frame", "removable covers": "yes"}),
    dict(sku="KAB-L", name="Kabini L-Shaped Sectional", category="sofa", collection="Kabini",
         description="A five-seat sectional with a reversible chaise for flexible layouts.",
         price=Decimal("124000"), dimensions="W 270 × D 170 × H 84 cm",
         materials=["solid acacia wood frame", "high-resilience foam", "linen-cotton blend upholstery"],
         finishes=["Sage", "Oat"], verified_attributes={"warranty": "5 years on the frame", "reversible chaise": "yes"}),
    dict(sku="KAB-2S", name="Kabini Loveseat", category="sofa", collection="Kabini",
         description="A compact two-seater for studies, balconies and smaller living rooms.",
         price=Decimal("56900"), dimensions="W 150 × D 92 × H 84 cm",
         materials=["solid acacia wood frame", "high-resilience foam", "linen-cotton blend upholstery"],
         finishes=["Sage", "Oat", "Terracotta"], verified_attributes={"warranty": "5 years on the frame"}),
    dict(sku="HEB-CT", name="Hebbal Coffee Table", category="coffee table", collection="Hebbal",
         description="Round coffee table with a woven cane shelf.", price=Decimal("18900"),
         dimensions="Ø 90 × H 42 cm", materials=["mango wood", "cane"], finishes=["Natural", "Walnut stain"],
         verified_attributes={}),
    dict(sku="NAN-QB", name="Nandi Queen Bed", category="bed", collection="Nandi",
         description="Queen bed with a slatted headboard and under-bed clearance for storage boxes.",
         price=Decimal("64000"), dimensions="W 165 × L 210 × H 105 cm", materials=["sheesham wood"],
         finishes=["Honey", "Dark walnut"], verified_attributes={"warranty": "3 years on the frame"}),
    dict(sku="COO-AC", name="Coorg Accent Chair", category="accent chair", collection="Coorg",
         description="A rounded lounge chair with a rubberwood base.", price=Decimal("24500"),
         dimensions="W 76 × D 80 × H 78 cm", materials=["rubberwood", "boucle"], finishes=["Ivory", "Moss"],
         verified_attributes={}),
]

PERSONAS = [
    dict(name="First-home couple", description="Late 20s–30s, just bought a 2BHK; furnishing room by room.",
         goals="Furniture that fits and lasts; clear prices.", pain_points="Unsure what fits; afraid of bulky sofas.",
         preferred_platforms=["instagram", "pinterest"]),
    dict(name="Upgrading family", description="Mid 30s–40s, moving to a bigger flat; replacing a starter sofa.",
         goals="Durable fabric, kid-friendly, good warranty.", pain_points="Stains, sagging cushions.",
         preferred_platforms=["instagram", "youtube"]),
    dict(name="Long-term renter", description="Professionals renting for 3+ years who want furniture that moves.",
         goals="Modular, easy to move, removable covers.", pain_points="Moving costs, landlord-furnished clutter.",
         preferred_platforms=["instagram"]),
]

TRENDS = [
    dict(topic="Compact living", statement="Fixture note: buyers in large Indian metros increasingly look for compact "
         "and modular living-room furniture that fits apartment layouts."),
    dict(topic="Festive refresh", statement="Fixture note: home décor and furniture purchases typically rise in the "
         "weeks before Diwali as households refresh living spaces."),
    dict(topic="Materials", statement="Fixture note: shoppers comparing high-ticket sofas ask about frame material, "
         "foam density and fabric care before buying."),
    dict(topic="Styling", statement="Fixture note: warm-minimal interiors (natural wood, soft neutrals) remain a "
         "common styling reference in home-décor content."),
]

COMPETITORS = [
    dict(name="Oakfern Home", notes="Fictional competitor (synthetic observations).", obs=[
        ("festive sale", "post", "Mega festive sale on sofas — limited time only.", "Shop the sale",
         ["sofa"], {"likes": 412, "comments": 18}),
        ("product spotlight", "post", "New arrival: the three-seater in velvet green.", "Shop now", ["sofa"],
         {"likes": 233, "comments": 6}),
        ("discount", "reel", "Up to 40% off this weekend.", "Link in bio", ["sofa", "bed"], {"likes": 520, "comments": 25}),
        ("product spotlight", "carousel", "Our bestselling beds in four finishes.", "DM to order", ["bed"],
         {"likes": 188, "comments": 4}),
    ]),
    dict(name="Casa Kindle", notes="Fictional competitor (synthetic observations).", obs=[
        ("luxury inspiration", "post", "Evenings in a sunlit living room.", "Explore the collection", ["sofa"],
         {"likes": 301, "comments": 9}),
        ("festive sale", "reel", "Festive edit: up to 30% off living room sets.", "Shop now", ["sofa", "coffee table"],
         {"likes": 455, "comments": 21}),
        ("new arrivals", "carousel", "Five new accent chairs for the season.", "Visit our store", ["accent chair"],
         None),
    ]),
]

HISTORY_POSTS = [
    # (variant, content_type, pillar, sku, days_ago)
    ("A", "post", "Product spotlight", "KAB-3S", 40), ("B", "carousel", "Styling tips", "KAB-3S", 39),
    ("A", "post", "Product spotlight", "NAN-QB", 37), ("B", "carousel", "Styling tips", "HEB-CT", 36),
    ("A", "post", "Product spotlight", "COO-AC", 34), ("B", "carousel", "Styling tips", "COO-AC", 33),
    ("A", "post", "Product spotlight", "KAB-2S", 31), ("B", "carousel", "Styling tips", "KAB-2S", 30),
]


def clear_workspace(db: Session, workspace_id: int) -> None:
    """Delete all marketing data in a workspace (users, members and settings stay)."""
    for model in (MetricSnapshot, PublishAttempt):
        ids = select(ContentItem.id).where(ContentItem.workspace_id == workspace_id)
        db.execute(delete(model).where(model.content_id.in_(ids)))
    for model in (ContentItem, Recommendation, Report, Experiment, Hypothesis, CompetitorObservation, Competitor,
                  ResearchFinding, Campaign, AgentRun, ChannelConnection, Persona, Product):
        db.execute(delete(model).where(model.workspace_id == workspace_id))
    for a in db.execute(select(Asset).where(Asset.workspace_id == workspace_id)).scalars().all():
        store().delete(a.storage_key)
    db.execute(delete(Asset).where(Asset.workspace_id == workspace_id))
    db.execute(delete(Brand).where(Brand.workspace_id == workspace_id))
    db.flush()


def seed(db: Session, workspace_id: int, user_id: int | None) -> dict:
    clear_workspace(db, workspace_id)
    now = utcnow()
    brand = Brand(workspace_id=workspace_id, is_synthetic=True, **BRAND)
    db.add(brand)
    db.flush()
    for p in PERSONAS:
        db.add(Persona(workspace_id=workspace_id, brand_id=brand.id, **p))
    products = {}
    for p in PRODUCTS:
        prod = Product(workspace_id=workspace_id, brand_id=brand.id, is_synthetic=True, **p)
        db.add(prod)
        products[p["sku"]] = prod
    db.flush()
    for t in TRENDS:
        db.add(ResearchFinding(workspace_id=workspace_id, brand_id=brand.id, topic=t["topic"], statement=t["statement"],
                               classification=EvidenceClass.SOURCE_REPORTED, source_type="fixture", source_url=None,
                               source_title="Demo fixture — synthetic trend note (not a real source)",
                               evidence_excerpt=t["statement"], is_synthetic=True))
    for c in COMPETITORS:
        comp = Competitor(workspace_id=workspace_id, brand_id=brand.id, name=c["name"], notes=c["notes"],
                          is_synthetic=True)
        db.add(comp)
        db.flush()
        for i, (theme, fmt, excerpt, cta, cats, eng) in enumerate(c["obs"]):
            db.add(CompetitorObservation(
                workspace_id=workspace_id, competitor_id=comp.id, source_type="fixture", source_url=None,
                observed_at=now - timedelta(days=2), published_at=now - timedelta(days=3 + i * 3),
                content_format=fmt, theme=theme, excerpt=excerpt, cta=cta, product_categories=cats,
                visible_engagement=eng, is_synthetic=True))
    conn = ChannelConnection(workspace_id=workspace_id, adapter="demo_instagram", platform="instagram",
                             name="Instagram (demo adapter)", account_id="demo-account",
                             account_label="@aranya.living.demo (simulated)", status=ConnectionStatus.DEMO,
                             last_verified_at=now, created_by=user_id)
    db.add(conn)
    db.flush()

    # Synthetic campaign history with an A/B experiment, so the adaptive loop has something to evaluate.
    hist = Campaign(workspace_id=workspace_id, brand_id=brand.id, name="Monsoon Cosy Corners (synthetic history)",
                    objective="Test whether styling carousels beat single product shots.",
                    audience=BRAND["audience"], geography="Bengaluru", platforms=["instagram"],
                    pillars=["Product spotlight", "Styling tips"], status="completed", is_synthetic=True,
                    start_date=(now - timedelta(days=41)).date(), end_date=(now - timedelta(days=29)).date(),
                    success_criteria=[{"metric": "engagement_rate_by_reach", "comparator": "relative_lift_gte",
                                       "target": 0.15, "variant": "B", "baseline": "A"}], created_by=user_id)
    db.add(hist)
    db.flush()
    hyp = Hypothesis(workspace_id=workspace_id, campaign_id=hist.id, statement="Styling-tip carousels earn a higher "
                     "engagement rate by reach than single product shots.", mechanism="Useful posts get saved/shared.",
                     uncertainty="Synthetic history.", validation_method="A/B, 4 posts per variant.",
                     status="selected", selected=True, rank=1)
    db.add(hyp)
    db.flush()
    exp = Experiment(workspace_id=workspace_id, campaign_id=hist.id, hypothesis_id=hyp.id,
                     name="Styling carousels vs single product shots (synthetic history)",
                     variants=[{"label": "A", "description": "Single product shot"},
                               {"label": "B", "description": "Styling-tips carousel"}],
                     success_criteria=hist.success_criteria, min_sample_per_variant=3, status="running",
                     is_synthetic=True)
    db.add(exp)
    db.flush()
    adapter = DemoInstagramAdapter()
    ctx = ConnectionContext(connection_id=conn.id, account_id="demo-account", config={}, credentials={})
    for idx, (variant, ctype, pillar, sku, days_ago) in enumerate(HISTORY_POSTS):
        p = products[sku]
        when = datetime.combine((now - timedelta(days=days_ago)).date(), time(13, 30))
        asset = make_placeholder(db, workspace_id=workspace_id, brand_id=brand.id, title=p.name,
                                 brief=f"{pillar} — {p.name}", colors=brand.colors, synthetic=True)
        item = ContentItem(
            workspace_id=workspace_id, brand_id=brand.id, campaign_id=hist.id, experiment_id=exp.id,
            variant_label=variant, platform="instagram", content_type=ctype, pillar=pillar,
            title=f"{pillar}: {p.name}", hook=f"{'Meet the' if variant == 'A' else '3 ways to style the'} {p.name}",
            caption=f"{p.description}" if variant == "A" else "Layer textures, ground it with a rug, add warm light.",
            hashtags=["#AranyaLiving", "#BengaluruHomes"], cta="Save this for later", product_ids=[p.id],
            asset_id=asset.id, status=ContentStatus.PUBLISHED, planned_at=when, scheduled_at=when,
            published_at=when, connection_id=conn.id, external_id=f"demo-ig-hist-{idx}", publish_verified=True,
            generated_by="demo-fixture", approved_version=1, approved_at=when - timedelta(days=1),
            approved_by=user_id, is_synthetic=True, created_by=user_id)
        db.add(item)
        db.flush()
        add_revision(db, item, "demo-fixture", user_id)
        m = adapter.fetch_metrics(ctx, item.external_id, hours_since=days_ago * 24,
                                  hints={"content_type": ctype, "pillar": pillar})
        db.add(MetricSnapshot(content_id=item.id, captured_at=when + timedelta(days=7), reach=m.reach, views=m.views,
                              likes=m.likes, comments=m.comments, shares=m.shares, saves=m.saves,
                              profile_visits=m.profile_visits, source="synthetic", raw=m.raw))
        db.add(PublishAttempt(content_id=item.id, connection_id=conn.id, adapter="demo_instagram", live=False,
                              idempotency_key=f"{item.id}:v1", success=True, external_id=item.external_id,
                              provider_status="SIMULATED_PUBLISHED", summary="Synthetic history.",
                              attempted_at=when))
    audit.record(db, "demo.seeded", workspace_id=workspace_id, user_id=user_id)
    db.flush()
    return {"brand_id": brand.id, "products": len(products), "history_campaign_id": hist.id, "experiment_id": exp.id}


DEMO_GOAL = ("Create a seven-day Instagram campaign for our new Kabini sofa collection aimed at urban homeowners in "
             "Bengaluru ahead of Diwali.")
EVAL_GOAL = "Evaluate last month's results and recommend what to change next week."
