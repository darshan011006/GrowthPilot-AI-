"""What each of the seven destination platforms supports, as data.

Used by validation (constraints), the Distribution role (variants and readiness), the renderer (sizes), and the
Integrations page (requirements and status). ``verified`` says how each spec was checked; anything marked
"prior knowledge" must be re-checked against the platform's current docs before going live.

Live adapters: Instagram and Facebook Pages are implemented (mock-tested, not yet verified with real accounts).
Pinterest, X, LinkedIn, YouTube and Threads have specs and simulated (demo) adapters only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class MediaFormat:
    width: int
    height: int
    label: str

    @property
    def ratio(self) -> float:
        return self.width / self.height


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    label: str
    content_types: tuple[str, ...]  # what the API can publish (our types: post, carousel, text, video)
    caption_max: int
    hashtags_max: int | None
    carousel_min: int = 2
    carousel_max: int = 0  # 0 = no carousel
    aspect_min: float = 0.5
    aspect_max: float = 2.0
    image_types: tuple[str, ...] = ("image/jpeg", "image/png")
    image_max_bytes: int = 8 * 1024 * 1024
    render: MediaFormat = MediaFormat(1080, 1350, "4:5 portrait")
    requires_media: bool = True
    link_in_caption: bool = True
    tone: str = ""
    audience_note: str = ""
    auth: str = ""
    scopes: tuple[str, ...] = ()
    eligibility: str = ""
    publish_ops: str = ""
    analytics: tuple[str, ...] = ()
    rate_limits: str = ""
    live_adapter: str = "not-implemented"  # implemented-unverified | verified | not-implemented
    needs_from_you: tuple[str, ...] = ()
    verified: str = ""
    sources: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["render"] = asdict(self.render) | {"ratio": round(self.render.ratio, 3)}
        return d


SPECS: dict[str, PlatformSpec] = {
    "instagram": PlatformSpec(
        key="instagram", label="Instagram", content_types=("post", "carousel"), caption_max=2200, hashtags_max=30,
        carousel_min=2, carousel_max=10, aspect_min=0.8, aspect_max=1.91, image_types=("image/jpeg",),
        render=MediaFormat(1080, 1350, "4:5 portrait"), link_in_caption=False,
        tone="Visual first; short hook in the first line; hashtags at the end.",
        audience_note="Discovery and saves; links in captions are not clickable.",
        auth="Instagram API with Instagram Login (OAuth 2.0)",
        scopes=("instagram_business_basic", "instagram_business_content_publish", "instagram_business_manage_insights"),
        eligibility="Instagram professional (Business or Creator) account; app in Live mode or the account added as "
                    "a tester; images reachable at a public HTTPS URL.",
        publish_ops="POST /{ig-id}/media → poll status_code → POST /{ig-id}/media_publish; carousels via children.",
        analytics=("reach", "likes", "comments", "shares", "saved", "views"),
        rate_limits="100 API-published posts per 24 hours (content_publishing_limit).",
        live_adapter="implemented-unverified",
        needs_from_you=("Meta developer app (META_APP_ID/META_APP_SECRET)", "Professional Instagram account",
                        "Public HTTPS BASE_URL", "Tester role or App Review for the scopes"),
        verified="Meta docs, 2026-10-24", sources=("https://developers.facebook.com/docs/instagram-platform",),
        notes=("Reels and stories need video upload, which isn't implemented.",)),
    "facebook": PlatformSpec(
        key="facebook", label="Facebook Page", content_types=("post", "carousel", "text"), caption_max=63206,
        hashtags_max=None, carousel_min=2, carousel_max=10, aspect_min=0.5, aspect_max=2.0,
        render=MediaFormat(1080, 1350, "4:5 portrait"), requires_media=False,
        tone="Conversational; a little more context than Instagram; one clear link or CTA.",
        audience_note="Community and local customers; clickable links work.",
        auth="Facebook Login for Business (OAuth 2.0) → Page access token",
        scopes=("pages_show_list", "pages_read_engagement", "pages_manage_posts"),
        eligibility="A Facebook Page where the connecting person can create content (CREATE_CONTENT task); "
                    "permissions beyond development use need Meta App Review.",
        publish_ops="POST /{page-id}/photos (url, message); multi-photo: upload with published=false then "
                    "POST /{page-id}/feed with attached_media; text: POST /{page-id}/feed.",
        analytics=("reactions", "comments", "shares"),
        rate_limits="Graph API rate limiting applies per Page/app (Business Use Case limits).",
        live_adapter="implemented-unverified",
        needs_from_you=("Same Meta app with Facebook Login for Business", "A Facebook Page you manage",
                        "Public HTTPS BASE_URL", "App Review for pages_manage_posts before real users"),
        verified="Meta Pages API docs (Posts guide), 2026-10-24; caption limit from prior knowledge",
        sources=("https://developers.facebook.com/docs/pages-api/posts",)),
    "pinterest": PlatformSpec(
        key="pinterest", label="Pinterest", content_types=("post", "carousel"), caption_max=500, hashtags_max=20,
        carousel_min=2, carousel_max=5, aspect_min=0.5, aspect_max=1.0, render=MediaFormat(1000, 1500, "2:3 portrait"),
        tone="Search-friendly title and description; describe the use, not the hype.",
        audience_note="Planning and saving ideas; links drive site visits.",
        auth="Pinterest OAuth 2.0", scopes=("boards:read", "pins:write"),
        eligibility="Pinterest business account; app approved for Standard access to publish beyond trial.",
        publish_ops="POST /v5/pins with board_id, title (≤100), description, link, alt_text, media_source image_url.",
        analytics=("impressions", "saves", "pin clicks", "outbound clicks"),
        rate_limits="Per-app and per-user limits; trial access is restricted.",
        needs_from_you=("Pinterest developer app", "Business account and a board", "Standard access approval"),
        verified="Prior knowledge plus third-party guides; title/description limits need checking",
        sources=("https://developers.pinterest.com/docs/api/v5/",)),
    "x": PlatformSpec(
        key="x", label="X", content_types=("post", "text"), caption_max=280, hashtags_max=2, carousel_max=4,
        carousel_min=2, render=MediaFormat(1600, 900, "16:9 landscape"), requires_media=False,
        tone="Short and direct; one idea; at most one or two hashtags.",
        audience_note="Fast-moving conversation; links count toward the limit.",
        auth="OAuth 2.0 with PKCE (user context)", scopes=("tweet.write", "users.read", "media.write"),
        eligibility="An X developer account on a tier that allows posting; costs depend on the current plan.",
        publish_ops="Upload media, then POST /2/tweets with media ids.",
        analytics=("impressions", "likes", "reposts", "replies"),
        rate_limits="Depends on the API plan.",
        needs_from_you=("X developer account and paid/eligible access tier", "OAuth client ID and secret for your app"),
        verified="Prior knowledge; check current X API plans and limits",
        sources=("https://docs.x.com/x-api",),
        notes=("280 characters for standard accounts.",)),
    "linkedin": PlatformSpec(
        key="linkedin", label="LinkedIn", content_types=("post", "text"), caption_max=3000, hashtags_max=5,
        carousel_max=0, render=MediaFormat(1200, 1200, "1:1 square"), requires_media=False,
        tone="Professional and informative; the story behind the brand or craft.",
        audience_note="Business audience; suits brand story, B2B and hiring more than product pushes.",
        auth="LinkedIn OAuth 2.0 (3-legged)", scopes=("w_organization_social", "r_organization_social"),
        eligibility="Admin of a LinkedIn Page; Community Management API access approved by LinkedIn.",
        publish_ops="Upload via the Images API, then POST /rest/posts with commentary and image urn.",
        analytics=("impressions", "clicks", "reactions", "comments", "shares"),
        rate_limits="Daily application and member limits.",
        needs_from_you=("LinkedIn developer app", "Community Management API approval", "Page admin rights"),
        verified="Prior knowledge; check LinkedIn's current Posts API docs",
        sources=("https://learn.microsoft.com/linkedin/marketing/community-management/shares/posts-api",)),
    "youtube": PlatformSpec(
        key="youtube", label="YouTube", content_types=("video",), caption_max=5000, hashtags_max=15, carousel_max=0,
        render=MediaFormat(1280, 720, "16:9 thumbnail"), requires_media=True,
        tone="Title plus a description that explains what viewers will learn.",
        audience_note="Video only; image creatives become a Shorts brief and thumbnail.",
        auth="Google OAuth 2.0", scopes=("https://www.googleapis.com/auth/youtube.upload",),
        eligibility="A YouTube channel; uploads from unverified API projects are restricted to private until the "
                    "project passes Google's audit.",
        publish_ops="videos.insert (resumable upload).",
        analytics=("views", "likes", "comments", "watch time"),
        rate_limits="Quota: an upload costs about 1,600 of the default 10,000 units per day.",
        needs_from_you=("Google Cloud project with YouTube Data API", "OAuth consent screen", "A video file"),
        verified="Prior knowledge; check YouTube Data API quota docs",
        sources=("https://developers.google.com/youtube/v3/docs/videos/insert",),
        notes=("GrowthPilot doesn't produce video; YouTube variants are briefs and can't be published.",)),
    "threads": PlatformSpec(
        key="threads", label="Threads", content_types=("post", "carousel", "text"), caption_max=500, hashtags_max=1,
        carousel_min=2, carousel_max=20, render=MediaFormat(1080, 1350, "4:5 portrait"), requires_media=False,
        tone="Casual and conversational; ask a question; one topic tag.",
        audience_note="Conversation; text-first posts do well.",
        auth="Threads API (Meta OAuth 2.0)", scopes=("threads_basic", "threads_content_publish"),
        eligibility="A Threads profile; Meta app with the Threads use case.",
        publish_ops="POST /{threads-user-id}/threads → POST /{threads-user-id}/threads_publish; carousels via children.",
        analytics=("views", "likes", "replies", "reposts", "quotes"),
        rate_limits="250 API-published posts per 24 hours (carousels count as one).",
        needs_from_you=("Meta app with the Threads API use case", "Threads profile authorisation"),
        verified="Meta Threads docs (posts), 2026-10-24; topic-tag limit from a third-party guide",
        sources=("https://developers.facebook.com/docs/threads/posts",),
        notes=("Text limit is 500 characters; emojis count by UTF-8 bytes.",)),
}

ORDER = ["instagram", "facebook", "pinterest", "x", "linkedin", "youtube", "threads"]


def spec(platform: str) -> PlatformSpec | None:
    return SPECS.get(platform)


def caption_length(text: str, platform: str) -> int:
    """Threads counts emoji by UTF-8 bytes; others count characters."""
    if platform == "threads":
        return sum(len(ch.encode("utf-8")) if ord(ch) > 0xFFFF else 1 for ch in text)
    return len(text)
