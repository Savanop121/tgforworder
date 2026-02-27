# ============================================
#  Advanced Message Filter Engine
#  - Weighted Ad/Spam Scoring
#  - Smart Footer Boundary Detection
#  - Welcome/Service Message Filter
# ============================================

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
#  1. AD / SPAM DETECTION — Weighted Scoring
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class AdKeyword:
    """Keyword with weight for scoring."""
    pattern: str
    weight: int
    category: str


# Categorized keywords with weights (higher = more indicative of spam)
AD_KEYWORDS = [
    # ── Gambling / Casino (high confidence) ──
    AdKeyword("彩票", 4, "gambling"),
    AdKeyword("赔率", 4, "gambling"),
    AdKeyword("返水", 5, "gambling"),
    AdKeyword("娱乐城", 5, "gambling"),
    AdKeyword("特码", 5, "gambling"),
    AdKeyword("打码", 4, "gambling"),
    AdKeyword("高赔率", 5, "gambling"),
    AdKeyword("高返水", 5, "gambling"),
    AdKeyword("彩金", 4, "gambling"),
    AdKeyword("开奖", 4, "gambling"),
    AdKeyword("下注", 4, "gambling"),
    AdKeyword("投注", 4, "gambling"),
    AdKeyword("百家乐", 5, "gambling"),
    AdKeyword("老虎机", 5, "gambling"),
    AdKeyword("棋牌", 4, "gambling"),
    AdKeyword("真人荷官", 5, "gambling"),
    AdKeyword("体育博彩", 5, "gambling"),

    # ── Registration / Deposit Promos ──
    AdKeyword("注册就送", 5, "promo"),
    AdKeyword("首存", 5, "promo"),
    AdKeyword("二存", 4, "promo"),
    AdKeyword("三存", 4, "promo"),
    AdKeyword("充值", 3, "promo"),
    AdKeyword("赠送", 3, "promo"),
    AdKeyword("优惠", 2, "promo"),
    AdKeyword("存款", 3, "promo"),
    AdKeyword("笔笔送", 5, "promo"),
    AdKeyword("无上限", 4, "promo"),

    # ── Service / Official Accounts ──
    AdKeyword("官方客服", 4, "service"),
    AdKeyword("官方飞投", 5, "service"),
    AdKeyword("飞投", 4, "service"),
    AdKeyword("福利频道", 4, "service"),
    AdKeyword("注册网址", 5, "service"),
    AdKeyword("注册入口", 5, "service"),
    AdKeyword("彩票客服", 5, "service"),
    AdKeyword("彩票入口", 5, "service"),
    AdKeyword("验资", 4, "service"),
    AdKeyword("担保", 3, "service"),

    # ── Crypto / Wallet Scams ──
    AdKeyword("NO钱包", 5, "crypto"),
    AdKeyword("WG联名", 5, "crypto"),
    AdKeyword("USDT", 2, "crypto"),
    AdKeyword("人民币", 1, "crypto"),

    # ── Generic Ad Calls-to-Action (low weight, needs more signals) ──
    AdKeyword("点击查看", 2, "cta"),
    AdKeyword("立即注册", 3, "cta"),
    AdKeyword("立即加入", 2, "cta"),
    AdKeyword("立即领取", 3, "cta"),
    AdKeyword("立即下载", 2, "cta"),
    AdKeyword("点击领取", 3, "cta"),
    AdKeyword("VIP升级", 3, "cta"),
    AdKeyword("新会员", 2, "promo"),
    AdKeyword("老会员", 2, "promo"),
]

# Score threshold to classify as spam
AD_SCORE_THRESHOLD = 10

# Known ad domain patterns
AD_DOMAIN_PATTERNS = [
    r'n9\.com', r'n9cp', r'566676\.vip', r'\.top/',
    r'\.vip/', r'\.bet/', r'\.casino/',
]


def _calculate_ad_score(text: str) -> tuple[int, list[str]]:
    """
    Calculate spam score using weighted keyword matching.
    Returns (score, list of matched categories).
    """
    score = 0
    matched_categories = set()

    for kw in AD_KEYWORDS:
        if kw.pattern.lower() in text.lower():
            score += kw.weight
            matched_categories.add(kw.category)

    # BONUS: Multiple categories = more likely spam (cross-category signal)
    if len(matched_categories) >= 3:
        score += 5

    # BONUS: Ad domain URLs detected
    for pattern in AD_DOMAIN_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            score += 4

    # BONUS: Extremely high emoji density (typical of casino ads)
    emoji_ratio = _emoji_density(text)
    if emoji_ratio > 0.15 and score > 0:
        score += 3

    # BONUS: Lots of URLs + short text (link spam)
    urls = re.findall(r'https?://\S+', text)
    lines = [l for l in text.strip().split('\n') if l.strip()]
    if len(urls) >= 5 and len(lines) <= 25:
        score += 5

    return score, list(matched_categories)


def _emoji_density(text: str) -> float:
    """Calculate what fraction of the text is emoji characters."""
    if not text:
        return 0.0
    # Match common emoji unicode ranges
    emoji_pattern = re.compile(
        "[\U0001F300-\U0001F9FF"   # Misc symbols, emoticons
        "\U00002600-\U000027BF"    # Misc symbols
        "\U0000FE00-\U0000FE0F"    # Variation selectors
        "\U0001FA00-\U0001FA6F"    # Chess symbols
        "\U0001FA70-\U0001FAFF"    # Symbols extended-A
        "\u200d"                   # Zero-width joiner
        "\u2640-\u2642"            # Gender symbols
        "\u2300-\u23FF"            # Misc technical
        "\uFE0F"                   # Variation selector
        "]+", re.UNICODE
    )
    emojis = emoji_pattern.findall(text)
    emoji_chars = sum(len(e) for e in emojis)
    return emoji_chars / max(len(text), 1)


def is_ad_or_spam(text: str) -> bool:
    """
    Advanced ad/spam detection using weighted scoring.
    Returns True if message should be skipped.
    """
    if not text:
        return False

    score, categories = _calculate_ad_score(text)

    if score >= AD_SCORE_THRESHOLD:
        logger.info(
            f"[FILTER] Ad detected (score: {score}, threshold: {AD_SCORE_THRESHOLD}, "
            f"categories: {', '.join(categories)})"
        )
        return True

    return False


# ══════════════════════════════════════════════
#  2. WELCOME / SERVICE MESSAGE DETECTION
# ══════════════════════════════════════════════

WELCOME_PATTERNS = [
    # Chinese welcome messages
    r"欢迎来到",
    r"欢迎加入",
    r"欢迎.*加入.*群",
    r"已加入群组",
    r"加入了群组",
    r"成功加入",

    # English welcome messages
    r"welcome\s+to\b",
    r"\bhas\s+joined\b",
    r"\bjust\s+joined\b",
    r"welcome\s+aboard",
    r"welcome\s+new\s+member",

    # Bot join/service messages
    r"被邀请加入",
    r"invited\s+to\s+join",
]


def is_welcome_message(text: str) -> bool:
    """
    Detects welcome/join/service messages.
    These are typically auto-generated and short.
    """
    if not text:
        return False

    # Welcome messages are always short
    if len(text) > 300:
        return False

    for pattern in WELCOME_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.info("[FILTER] Welcome/join message detected, skipping")
            return True

    return False


# ══════════════════════════════════════════════
#  3. SMART FOOTER DETECTION & REPLACEMENT
# ══════════════════════════════════════════════

# Footer indicator patterns — each with a confidence score
@dataclass(frozen=True)
class FooterPattern:
    pattern: str
    score: int


FOOTER_PATTERNS = [
    # High confidence — almost certainly footer
    FooterPattern(r't\.me/\+?\w+', 10),                    # t.me links
    FooterPattern(r'@\w{4,}', 6),                          # @username mentions
    FooterPattern(r'https?://t\.me/', 10),                  # Full telegram URLs
    FooterPattern(r'https?://\S+', 4),                      # Any URL

    # Medium confidence — likely footer
    FooterPattern(r'订阅|频道|群聊|加入群', 7),              # Subscribe/channel/join
    FooterPattern(r'广告|爆料|投稿|报料|報料', 7),            # Ads/tips/submissions
    FooterPattern(r'关注|關注|联系|聯繫', 6),                 # Follow/contact
    FooterPattern(r'subscribe|channel|follow|contact', 5),  # English equivalents

    # Emoji-led promotional lines
    FooterPattern(r'^[\s]*📣', 8),
    FooterPattern(r'^[\s]*💬', 7),
    FooterPattern(r'^[\s]*🔗', 8),
    FooterPattern(r'^[\s]*📢', 8),
    FooterPattern(r'^[\s]*😍', 5),
    FooterPattern(r'^[\s]*👉', 6),
    FooterPattern(r'^[\s]*📌', 6),
    FooterPattern(r'^[\s]*🔔', 6),
    FooterPattern(r'^[\s]*☮️', 6),
    FooterPattern(r'^[\s]*☎️', 6),
    FooterPattern(r'^[\s]*🌐', 6),
    FooterPattern(r'^[\s]*📲', 6),
    FooterPattern(r'^[\s]*✅', 4),
    FooterPattern(r'^[\s]*⬇️', 5),
    FooterPattern(r'^[\s]*↓', 5),
]

# Line needs this score to be considered footer
FOOTER_LINE_THRESHOLD = 6

# Maximum lines to scan upward from bottom for footer detection
MAX_FOOTER_SCAN = 15


def _score_footer_line(line: str) -> int:
    """Calculate how likely a line is part of a footer."""
    stripped = line.strip()
    if not stripped:
        return 0  # Empty lines scored by context

    total = 0
    for fp in FOOTER_PATTERNS:
        if re.search(fp.pattern, stripped, re.IGNORECASE):
            total += fp.score

    return total


def _find_footer_boundary(lines: list[str]) -> int:
    """
    Scans from bottom upward to find where footer starts.
    Returns index of first footer line.
    Uses scoring + context to make smart decisions.
    """
    total_lines = len(lines)
    if total_lines == 0:
        return total_lines

    # Don't scan more than MAX_FOOTER_SCAN lines from bottom
    scan_start = max(0, total_lines - MAX_FOOTER_SCAN)

    # Score all candidate lines (bottom section)
    line_scores = []
    for i in range(scan_start, total_lines):
        score = _score_footer_line(lines[i])
        line_scores.append((i, score, lines[i].strip()))

    if not line_scores:
        return total_lines

    # Find the highest contiguous footer block from bottom
    footer_start = total_lines  # default: no footer
    found_footer_line = False

    for i in range(len(line_scores) - 1, -1, -1):
        idx, score, text = line_scores[i]

        if score >= FOOTER_LINE_THRESHOLD:
            # This is a footer line
            footer_start = idx
            found_footer_line = True
        elif not text:
            # Empty line — if we already found footer below, include it
            if found_footer_line:
                footer_start = idx
        else:
            # Non-footer, non-empty line
            if found_footer_line:
                # We hit content — stop scanning
                break

    return footer_start


def replace_footer(text: str, custom_footer: str) -> str:
    """
    Detects and removes existing footer, appends custom footer.
    Uses scored pattern matching for smart boundary detection.
    """
    if not text:
        return custom_footer.strip()

    lines = text.split('\n')

    # Find where footer starts
    footer_boundary = _find_footer_boundary(lines)

    # Extract content (everything before footer)
    content_lines = lines[:footer_boundary]

    # Trim trailing empty lines from content
    while content_lines and not content_lines[-1].strip():
        content_lines.pop()

    content = '\n'.join(content_lines)

    # Build final text
    if content:
        return f"{content}\n\n{custom_footer.strip()}"
    else:
        # Message was entirely footer — just use custom footer
        return custom_footer.strip()


# ══════════════════════════════════════════════
#  4. MAIN ENTRY POINT
# ══════════════════════════════════════════════

def process_message_text(text: str, custom_footer: str) -> str | None:
    """
    Full message processing pipeline:
    1. Ad/spam check → return None to skip
    2. Welcome message check → return None to skip
    3. Footer replacement → return modified text

    Returns None = skip this message entirely
    Returns str  = forward with this modified text
    """
    if not text:
        # No text (media-only) — just add footer as caption
        return custom_footer.strip()

    # Stage 1: Ad/spam detection
    if is_ad_or_spam(text):
        return None

    # Stage 2: Welcome/service message detection
    if is_welcome_message(text):
        return None

    # Stage 3: Footer replacement
    return replace_footer(text, custom_footer)
