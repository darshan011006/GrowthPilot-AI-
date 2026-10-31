"""create_content_brief: rule tests on mocked facts, plus one end-to-end run on the Poojaloka demo data."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from growthpilot.agent import briefs as B

TODAY = date(2026, 10, 31)


def facts(**kw) -> B.BriefFacts:
    base = dict(content_id=11, platform="instagram", platform_label="Instagram", content_type="post",
                size=(1080, 1350, "4:5 portrait"), link_in_caption=False, post_date=TODAY + timedelta(days=2),
                today=TODAY, pillar="Product showcase", pillar_kind="showcase", brand_name="Poojaloka",
                objective="saves_per_reach: grow saves", audience="Families in Bengaluru",
                colors=["#6B1420", "#C99A3D", "#FBF3E7", "#2B1810", "#D9722A"],
                categories=["Brass Collection", "Pooja Essentials"],
                product=B.ProductFacts(sku="brass-diya", name="Brass Diya Large", category="Brass Collection",
                                       materials=["brass"], price=Decimal("499.00"), price_ok=True, trust="stock"),
                prohibited=["100% pure", "miracle"], restricted=["Since 1980"])
    base.update(kw)
    return B.BriefFacts(**base)


def real_photo(**kw) -> B.ProductFacts:
    return B.ProductFacts(**({"sku": "brass-diya", "name": "Brass Diya Large", "category": "Brass Collection",
                              "materials": ["brass"], "price": Decimal("499.00"), "price_ok": True,
                              "trust": "real_match", "photo_asset_id": 7} | kw))


def build(f: B.BriefFacts, role: str = "text_only") -> B.CreativeBrief:
    out = B.brief_with_retry(f, role)
    assert not out.fallback, out.attempts
    assert B.check_brief(out.brief, f) == []
    return out.brief


# ── festivals ────────────────────────────────────────────────────────────


def test_verified_festival_within_21_days_is_used():
    f = facts(pillar="Festival guide", pillar_kind="guide", wants_festival=True,
              festivals=[{"name": "Deepavali", "start": date(2026, 11, 8), "end": date(2026, 11, 8),
                          "source": "Poojaloka festival calendar"}])
    b = build(f)
    assert b.festival and b.festival.name == "Deepavali" and b.festival.start == date(2026, 11, 8)
    assert b.angle == "festival_prep" and "Deepavali" in b.headline
    assert not any(i.code == "festival_date_missing" for i in b.data_issues)


def test_canva_handoff_adapter_preserves_contract_and_evidence():
    f = facts(images=[B.ImageOption("brand_site", 7, "real_match", "brass-diya")],
              product=real_photo())
    b = build(f, "image")
    payload = B.to_canva_handoff(b)
    assert payload["schema_version"] == 1
    assert payload["content_id"] == b.content_id
    assert payload["format"] == "instagram_post"
    assert payload["required_text"] == b.required_text
    assert payload["image_policy"] == "must_use_images"
    assert payload["image_refs"] == [{"source": "brand_site", "asset_id": 7,
                                       "product_sku": "brass-diya", "trust": "real_match"}]
    assert payload["claims_allowed"] == [c.text for c in b.claims_allowed]
    assert payload["claim_evidence"] == [c.model_dump(mode="json") for c in b.claims_allowed]
    assert payload["canonical"]["schema_version"] == "1.0"
    assert "Poojaloka" in payload["canva_query"]


def test_canva_handoff_legacy_brief_defaults_image_trust_and_null_festival():
    b = build(facts(), "text_only")
    legacy = B.CreativeBrief.model_validate(b.model_dump(exclude={"data_issues"}))
    payload = B.to_canva_handoff(legacy)
    assert payload["festival"] is None
    assert payload["image_refs"] == []
    assert payload["image_policy"] == "text_only"
    assert payload["banned"] == legacy.banned


def test_festival_beyond_21_days_or_undated_stays_evergreen_and_is_reported():
    far = facts(pillar="Festival guide", pillar_kind="guide", wants_festival=True, undated_festivals=["Navaratri"],
                festivals=[{"name": "Sankranti", "start": TODAY + timedelta(days=40),
                            "end": TODAY + timedelta(days=40), "source": "calendar"}],
                festival_names=["Sankranti", "Navaratri", "Diwali"])
    b = build(far)
    assert b.festival is None and b.angle != "festival_prep"
    issue = next(i for i in b.data_issues if i.code == "festival_date_missing")
    assert "Navaratri" in issue.message


def test_past_festival_is_never_used():
    f = facts(pillar="Festival guide", pillar_kind="guide", wants_festival=True,
              festivals=[{"name": "Navaratri", "start": date(2026, 10, 11), "end": date(2026, 10, 20),
                          "source": "calendar"}])
    assert B.festival_for(f) is None
    b = build(f)
    assert b.festival is None
    # A brief claiming that past festival is rejected.
    bad = b.model_dump() | {"festival": {"name": "Navaratri", "start": "2026-10-11", "end": "2026-10-20",
                                         "source": "calendar"}}
    assert "festival is in the past" in B.check_brief(B.CreativeBrief.model_validate(bad), f)


def test_undated_festival_name_cannot_appear_on_an_evergreen_brief():
    f = facts(festival_names=["Deepavali"])
    b = build(f)
    bad = b.model_dump()
    bad["headline"] = "Get ready for Deepavali"
    bad["required_text"] = [bad["headline"], *bad["required_text"][1:]]
    bad["canva_query"] = bad["canva_query"].replace(f'"{b.headline}"', f'"{bad["headline"]}"')
    errs = B.check_brief(B.CreativeBrief.model_validate(bad), f)
    assert any("without a verified date" in e for e in errs)


def test_checked_festival_dates_have_sources_and_never_return_past_dates():
    from growthpilot.services import festival_dates as F

    assert F.festival_key("Krishna Janmashtami") == "janmashtami" and F.festival_key("Diwali") == "deepavali"
    assert F.next_verified("deepavali", date(2026, 10, 31))["start"] == date(2026, 11, 8)
    assert F.next_verified("Deepavali", date(2026, 11, 9))["start"] == date(2027, 10, 29)
    assert F.next_verified("krishna-janmashtami", date(2026, 10, 31)) is None  # 4 Sep 2026 has passed
    assert F.next_verified("navaratri", date(2026, 1, 1)) is None  # no checked start date
    for occurrences in F.VERIFIED.values():
        for o in occurrences:
            assert o["source"] and o["end"] >= o["start"]


# ── images ───────────────────────────────────────────────────────────────


def test_real_store_photo_is_must_use_and_kept_unaltered():
    f = facts(product=real_photo(), images=[B.ImageOption("brand_site", 7, "real_match", "brass-diya")])
    b = build(f, "image")
    assert b.image_policy == "must_use_images" and b.style.composition == "photo_led"
    assert b.image_refs[0].model_dump() == {"source": "brand_site", "asset_id": 7, "product_sku": "brass-diya"}
    assert "unaltered" in b.canva_query and "asset 7" in b.canva_query


def test_stock_photo_is_never_used_and_the_slot_becomes_text_only():
    f = facts()  # product trust is "stock", so the tool offers no image options
    b = build(f, "image")
    assert b.image_policy == "text_only" and b.image_refs == []
    assert "no product photos, stock photos" in b.canva_query
    assert any(i.code == "mix_downgraded" for i in b.data_issues)


def test_missing_trust_metadata_means_may_use_and_human_review():
    f = facts(product=real_photo(trust="unknown"), images=[B.ImageOption("brand_site", 9, "unknown", "brass-diya")])
    b = build(f, "image")
    assert b.image_policy == "may_use_images" and b.needs_human_review
    assert any(i.code == "photo_trust_missing" and i.needs_review for i in b.data_issues)
    # must_use_images is refused for an image whose trust isn't confirmed.
    bad = B.CreativeBrief.model_validate(b.model_dump() | {"image_policy": "must_use_images", "canva_query":
                                                          b.canva_query + " Keep it unaltered."})
    assert any("must_use_images needs" in e for e in B.check_brief(bad, f))


def test_team_upload_linked_to_the_post_can_be_required():
    f = facts(product=None, images=[B.ImageOption("uploaded", 31, "uploaded")])
    b = build(f, "combination")
    assert b.image_policy == "must_use_images" and b.style.composition == "photo_plus_text"
    assert b.image_refs[0].source == "uploaded" and b.image_refs[0].asset_id == 31
    # An asset that isn't linked to this post can't be referenced.
    bad = B.CreativeBrief.model_validate(b.model_dump() | {"image_refs": [{"source": "uploaded", "asset_id": 99}],
                                                          "canva_query": b.canva_query.replace("asset 31",
                                                                                               "asset 99")})
    assert any("isn't a real photo or upload" in e for e in B.check_brief(bad, f))


# ── facts and claims ─────────────────────────────────────────────────────


def test_claims_are_traceable_to_product_data_and_missing_facts_are_not_invented():
    f = facts(product=B.ProductFacts(sku="kumkum", name="Kumkum", category="Pooja Essentials", trust="stock"))
    b = build(f)
    assert {c.field for c in b.claims_allowed} <= {"name", "category"}  # no price, material or size on record
    assert all(c.product_sku == "kumkum" for c in b.claims_allowed)
    tampered = b.model_dump()
    tampered["claims_allowed"] = [{"text": "Pure copper", "product_sku": "kumkum", "field": "materials",
                                   "value": "copper"}]
    assert any("doesn't match" in e for e in B.check_brief(B.CreativeBrief.model_validate(tampered), f))


def test_price_claim_only_with_fresh_unflagged_price_and_never_on_the_poster():
    fresh = build(facts(product=real_photo(trust="stock")))
    stale = build(facts(product=real_photo(trust="stock", price_ok=False)))
    assert fresh.angle in ("product_spotlight", "material_focus", "category_edit")
    assert any(c.field == "price" for c in fresh.claims_allowed)
    assert not any(c.field == "price" for c in stale.claims_allowed)
    assert "₹" not in " ".join(fresh.required_text)


def test_unsupported_offer_is_rejected_then_retried_then_falls_back():
    def offers(text):  # catalogue check that fails anything with an offer
        return ["Mentions a discount/offer that isn't an approved claim."] if "off" in text.lower() else []

    f = facts(claim_checker=offers)
    b = build(f)
    bad = b.model_dump()
    bad["tagline"] = "Flat 20% off this week at Poojaloka"
    bad["required_text"] = [b.headline, bad["tagline"], b.cta, "Poojaloka"]
    bad["canva_query"] = bad["canva_query"].replace(f'"{b.tagline}"', f'"{bad["tagline"]}"')
    errs = B.check_brief(B.CreativeBrief.model_validate(bad), f)
    assert any("price or offer" in e for e in errs) and any("catalogue check" in e for e in errs)

    calls = {"n": 0}

    def first_fails(text):
        calls["n"] += 1
        return ["Price ₹1 not in catalogue."] if calls["n"] == 1 else []

    out = B.brief_with_retry(facts(claim_checker=first_fails), "text_only")
    assert not out.fallback and len(out.attempts) == 1
    assert any(i.code == "validation_retry" for i in out.brief.data_issues)

    out = B.brief_with_retry(facts(claim_checker=lambda t: ["always fails"]), "image")
    assert out.fallback and len(out.attempts) == 2
    fb = out.brief
    assert fb.image_policy == "text_only" and fb.claims_allowed == [] and fb.festival is None
    assert fb.needs_human_review and any(i.code == "validation_failed" for i in fb.data_issues)


# ── religious content ────────────────────────────────────────────────────


def test_deity_product_is_not_named_pictured_or_claimed():
    idol = B.ProductFacts(sku="ganesha", name="Brass Ganesha Idol", category="Brass Collection", trust="real_match",
                          photo_asset_id=5, religious=True)
    f = facts(product=idol, images=[], issues=[{"code": "religious_concept", "message": "Idol product.",
                                                "needs_review": True}])
    b = build(f, "image")
    assert b.needs_human_review and b.image_refs == [] and b.claims_allowed == []
    assert "ganesha" not in json.dumps([b.headline, b.tagline, b.canva_query]).lower()
    assert b.angle in ("category_edit", "brand_promise")


def test_festival_named_after_a_deity_is_kept_out_of_the_prompt():
    f = facts(pillar="Festival guide", pillar_kind="guide", wants_festival=True,
              festivals=[{"name": "Krishna Janmashtami", "start": TODAY + timedelta(days=5),
                          "end": TODAY + timedelta(days=5), "source": "calendar"}])
    b = build(f)
    assert b.festival and b.festival.name == "Krishna Janmashtami"
    assert "krishna" not in (b.headline + b.tagline + b.canva_query).lower()
    assert b.needs_human_review and any(i.code == "religious_concept" for i in b.data_issues)


def test_religious_terms_in_copy_or_prompt_fail_validation():
    b = build(facts())
    with pytest.raises(ValidationError):
        B.CreativeBrief.model_validate(b.model_dump() | {"headline": "Lakshmi blessings at home", "required_text": [
            "Lakshmi blessings at home", b.tagline, b.cta, "Poojaloka"]})
    bad = B.CreativeBrief.model_validate(b.model_dump() | {"canva_query": b.canva_query + " Add an Om mantra."})
    assert any("religious terms" in e for e in B.check_brief(bad, facts()))
    assert B.religious_terms("ॐ नमः") and not B.religious_terms("Brass diya for Deepavali")


# ── repetition and QA feedback ───────────────────────────────────────────


def test_recent_angle_headline_tagline_layout_and_palette_are_not_repeated():
    first = build(facts())
    recent = [B.RecentPost(headline=first.headline, tagline=first.tagline, angle=first.angle,
                           layout=first.style.layout, palette=first.style.palette)]
    again = build(facts(recent=recent))
    assert again.angle != first.angle and again.headline != first.headline and again.tagline != first.tagline
    assert again.style.layout != first.style.layout and again.style.palette != first.style.palette
    copy = B.CreativeBrief.model_validate(first.model_dump())
    errs = B.check_brief(copy, facts(recent=recent))
    assert "headline repeats a recent post" in errs and "tagline repeats a recent post" in errs


def test_repeat_window_reuses_the_least_recent_option_when_all_are_used():
    choice, repeated = B.lru(["a", "b", "c"], ["a", "c", "b"])
    assert choice == "b" and repeated  # "b" was used longest ago
    assert B.lru(["a", "b"], ["a"]) == ("b", False)


def test_prior_qa_feedback_shapes_the_brief():
    qa = B.QA(short_headline=True, simple_layout=True, high_contrast=True, drop_price=True,
              notes=["earlier posters had text overlap"])
    b = build(facts(product=real_photo(trust="stock"), qa=qa))
    assert B.words(b.headline) <= B.HEADLINE_MAX_WORDS_QA
    assert b.style.layout in B.SIMPLE_LAYOUTS
    assert B.contrast(b.style.colors[0], b.style.colors[1]) >= 7
    assert not any(c.field == "price" for c in b.claims_allowed)
    assert "applies prior QA" in b.signals.reason


# ── schema ───────────────────────────────────────────────────────────────


def test_schema_is_strict():
    b = build(facts())
    data = b.model_dump(mode="json")
    assert B.validate_brief(json.dumps(data)).content_id == 11
    assert "Poojaloka" in data["required_text"] and "Poojaloka" in data["canva_query"]
    assert B.words(data["canva_query"]) <= B.QUERY_MAX_WORDS
    for t in data["required_text"]:
        assert f'"{t}"' in data["canva_query"]
    with pytest.raises(ValidationError):
        B.CreativeBrief.model_validate(data | {"unexpected": 1})
    with pytest.raises(ValidationError):
        B.CreativeBrief.model_validate(data | {"image_refs": [{"source": "uploaded", "asset_id": 3}]})  # text_only
    with pytest.raises(ValidationError):
        B.CreativeBrief.model_validate(data | {"cta": "Shop now and save this post"})
    with pytest.raises(ValidationError):
        B.CreativeBrief.model_validate(data | {"canva_query": data["canva_query"] + " word" * 120})
    with pytest.raises(ValidationError):
        B.CreativeBrief.model_validate(data | {"headline": "one two three four five six seven eight nine"})
    with pytest.raises(ValueError):
        B.validate_brief(data | {"required_text": [b.headline, b.tagline, b.cta, "Aranya"]})
    with pytest.raises(ValidationError):
        B.ImageRef(source="brand_site", asset_id=4)  # a store photo must name its product


# ── portfolio mix ────────────────────────────────────────────────────────


def test_weekly_mix_is_two_text_two_image_one_combination_where_photos_exist():
    slots = [(1, "carousel", "trusted"), (2, "post", "trusted"), (3, "carousel", "trusted"), (4, "post", "trusted"),
             (5, "post", "trusted")]
    roles, notes = B.plan_mix(slots)
    assert sorted(roles.values()) == ["combination", "image", "image", "text_only", "text_only"]
    assert roles[1] == "combination" and not notes  # combination prefers a carousel
    roles, notes = B.plan_mix([(1, "post", "none"), (2, "post", "trusted"), (3, "carousel", "none"),
                               (4, "post", "unknown"), (5, "carousel", "none")])
    assert roles[1] == roles[3] == roles[5] == "text_only"
    assert {roles[2], roles[4]} == {"image", "combination"} and notes  # shortfall is reported


# ── end to end on the Poojaloka demo data ────────────────────────────────


def test_demo_campaign_saves_valid_briefs_and_versions_them(poojaloka_seeded):
    from growthpilot.db import session_scope
    from growthpilot.demo.fixtures import DEMO_GOAL
    from growthpilot.models import ContentItem, ContentRevision, ContentStatus
    from growthpilot.services.content import update

    from .conftest import run_worker

    api = poojaloka_seeded
    rid = api.post("/api/agent/runs", json={"goal": DEMO_GOAL}).json()["id"]
    run_worker()
    run = api.get(f"/api/agent/runs/{rid}").json()
    step = next(s for s in run["steps"] if s["tool"] == "create_content_brief" and s["phase"] == "tool")
    assert step["status"] == "ok", step["message"]
    out = step["output"]
    codes = {i["code"] for i in out["data_issues"]}
    # No promotable demo product has a real store photo, so the image slots fall short (reported).
    assert "mix_shortfall" in codes
    # Navaratri has no checked date, so it is always reported.
    assert any(i["code"] == "festival_date_missing" and "Navaratri" in i["message"] for i in out["data_issues"])
    items = [api.get(f"/api/content/{cid}").json() for cid in out["content_ids"]]
    assert len(items) == 7
    for it in items:
        b = B.validate_brief(it["creative_brief"])
        assert b.content_id == it["id"] and b.image_policy == "text_only"
        if b.festival:  # only from the checked list, and only within the window of the post
            assert b.festival.name == "Deepavali" and b.festival.start == date(2026, 11, 8)
            assert "CAG" in b.festival.source and b.angle == "festival_prep"
        assert "Poojaloka" in b.required_text and "Poojaloka" in b.canva_query
    assert len({(i["creative_brief"]["headline"]) for i in items}) == len(items)

    with session_scope() as db:
        item = db.get(ContentItem, items[0]["id"])
        notes = [r.note for r in db.query(ContentRevision).filter_by(content_id=item.id)]
        assert any(n.startswith("Creative brief v1.0") for n in notes)
        # Approval is bound to the brief: changing it makes a new version and clears the approval.
        item.status, item.approved_version, item.approved_hash = ContentStatus.APPROVED, item.version, "x" * 64
        v = item.version
        changed = dict(item.creative_brief) | {"headline": "Your pooja space, simplified"}
        assert update(db, item, {"creative_brief": changed}, user_id=None, role="editor", source="test")
        assert item.version == v + 1 and item.status == ContentStatus.DRAFT and item.approved_version is None
        assert item.publish_authorized is False
