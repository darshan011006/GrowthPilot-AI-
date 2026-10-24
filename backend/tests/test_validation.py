from __future__ import annotations

from decimal import Decimal

import pytest

from growthpilot.models import Asset, Brand, ContentItem, Product
from growthpilot.services.validation import check_brand, check_platform, check_product_claims, final_caption


@pytest.fixture
def brand():
    return Brand(name="Aranya", approved_claims=["Free delivery within Bengaluru city limits"],
                 restricted_claims=["eco-friendly"], prohibited_messaging=["cheapest in India"])


@pytest.fixture
def sofa():
    return Product(id=1, sku="KAB-3S", name="Kabini 3-Seater Sofa", category="sofa", price=Decimal("78500"),
                   dimensions="W 210 × D 92 × H 84 cm", materials=["solid acacia wood frame", "linen-cotton blend"],
                   finishes=["Sage"], verified_attributes={"warranty": "5 years on the frame"})


def statuses(checks, code):
    return [c.status for c in checks if c.code == code]


def test_price_must_match_catalogue(brand, sofa):
    assert statuses(check_product_claims("Now ₹78,500.", brand, [sofa], [sofa]), "price") == ["pass"]
    assert statuses(check_product_claims("Only Rs 69,999!", brand, [sofa], [sofa]), "price") == ["fail"]


def test_offers_need_an_approved_claim(brand, sofa):
    assert "fail" in statuses(check_product_claims("Festive offers on the Kabini.", brand, [sofa], [sofa]), "offer")
    assert "fail" in statuses(check_product_claims("Flat 20% off this week.", brand, [sofa], [sofa]), "offer")


def test_approved_delivery_claim_passes_but_invented_one_fails(brand, sofa):
    ok = check_product_claims("Free delivery within Bengaluru city limits.", brand, [sofa], [sofa])
    assert statuses(ok, "availability") == ["pass"]
    bad = check_product_claims("Ships in 2 days, only 3 left!", brand, [sofa], [sofa])
    assert statuses(bad, "availability") == ["fail"]


def test_warranty_verified_against_attributes(brand, sofa):
    assert statuses(check_product_claims("Backed by a 5-year warranty.", brand, [sofa], [sofa]), "warranty") == ["pass"]
    assert statuses(check_product_claims("Comes with a 10-year warranty.", brand, [sofa], [sofa]), "warranty") == ["fail"]


def test_materials_and_dimensions(brand, sofa):
    checks = check_product_claims("Made of teak, 240 cm wide.", brand, [sofa], [sofa])
    assert "fail" in statuses(checks, "material")
    assert statuses(checks, "dimension") == ["fail"]
    checks = check_product_claims("Acacia frame, 210 cm wide, linen upholstery.", brand, [sofa], [sofa])
    assert set(statuses(checks, "material")) == {"pass"}
    assert statuses(checks, "dimension") == ["pass"]


def test_certifications_and_policy_lists(brand, sofa):
    checks = check_product_claims("FSC certified and the cheapest in India. Very eco-friendly.", brand, [sofa], [sofa])
    assert "fail" in statuses(checks, "certification")
    assert statuses(checks, "prohibited") == ["fail"]
    assert statuses(checks, "restricted") == ["warn"]


def _item(**kw):
    defaults = dict(id=1, workspace_id=1, platform="instagram", content_type="post", caption="A calm living room.",
                    hook="", cta="Visit us", hashtags=[], version=1)
    defaults.update(kw)
    return ContentItem(**defaults)


def test_brand_checks_catch_competitor_names_and_copying(brand):
    item = _item(caption="Better than Oakfern Home sofas.")
    assert "fail" in [c.status for c in check_brand(item, brand, ["Oakfern Home"], [])]
    copied = "Mega festive sale on sofas — limited time only. Shop the whole collection today."
    item = _item(caption=copied)
    assert any(c.code == "originality" for c in check_brand(item, brand, [], [copied]))


def test_platform_limits():
    jpeg = Asset(id=1, source="upload", content_type="image/jpeg", filename="a.jpg", width=1080, height=1350)
    ok = check_platform(_item(), [jpeg])
    assert not [c for c in ok if c.status == "fail"]
    many_tags = _item(hashtags=[f"#t{i}" for i in range(31)])
    assert "fail" in [c.status for c in check_platform(many_tags, [jpeg]) if c.code == "hashtags"]
    long_caption = _item(caption="x" * 2300)
    assert "fail" in [c.status for c in check_platform(long_caption, [jpeg]) if c.code == "caption_length"]
    reel = _item(content_type="reel")
    assert "fail" in [c.status for c in check_platform(reel, [jpeg])]
    wide = Asset(id=2, source="upload", content_type="image/jpeg", filename="w.jpg", width=3000, height=1000)
    assert "fail" in [c.status for c in check_platform(_item(), [wide]) if c.code == "aspect_ratio"]
    carousel_one = _item(content_type="carousel")
    assert "fail" in [c.status for c in check_platform(carousel_one, [jpeg]) if c.code == "media"]


def test_placeholder_is_warning_in_demo_and_failure_in_live(monkeypatch, tmp_path):
    from .conftest import _configure

    ph = Asset(id=1, source="placeholder", content_type="image/svg+xml", filename="p.svg", width=1080, height=1350)
    _configure(monkeypatch, tmp_path, "demo")
    assert [c.status for c in check_platform(_item(), [ph]) if c.code == "media"] == ["warn"]
    _configure(monkeypatch, tmp_path, "live")
    assert "fail" in [c.status for c in check_platform(_item(), [ph]) if c.code == "media"]


def test_final_caption_composition():
    item = _item(hook="Meet Kabini", caption="Deep seats.", cta="DM us", hashtags=["#Aranya"])
    assert final_caption(item) == "Meet Kabini\n\nDeep seats.\n\nDM us\n\n#Aranya"
