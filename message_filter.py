# ============================================
#  Advanced Message Filter Engine v2
#  - Weighted Ad/Spam Scoring (70+ keywords)
#  - Smart Footer Boundary Detection
#  - Welcome/Service Message Filter
#  - Separator-aware footer scanning
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
    pattern: str
    weight: int
    category: str


# 70+ categorized keywords with weights
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
    AdKeyword("六大版块", 4, "gambling"),
    AdKeyword("极速出款", 5, "gambling"),
    AdKeyword("安全稳定", 2, "gambling"),
    AdKeyword("应有尽有", 2, "gambling"),
    AdKeyword("全球公认", 3, "gambling"),
    AdKeyword("顶级平台", 4, "gambling"),
    AdKeyword("国际娱乐", 5, "gambling"),

    # ── Registration / Deposit Promos ──
    AdKeyword("注册就送", 5, "promo"),
    AdKeyword("注册登入", 5, "promo"),
    AdKeyword("首存", 5, "promo"),
    AdKeyword("二存", 4, "promo"),
    AdKeyword("三存", 4, "promo"),
    AdKeyword("充值", 3, "promo"),
    AdKeyword("赠送", 3, "promo"),
    AdKeyword("优惠", 2, "promo"),
    AdKeyword("存款", 3, "promo"),
    AdKeyword("笔笔送", 5, "promo"),
    AdKeyword("无上限", 4, "promo"),
    AdKeyword("惊喜奇遇", 3, "promo"),
    AdKeyword("新春纵享", 3, "promo"),
    AdKeyword("好运不掉线", 3, "promo"),
    AdKeyword("福泽岁岁长", 3, "promo"),
    AdKeyword("更多优惠活动", 3, "promo"),

    # ── Service / Official Accounts ──
    AdKeyword("官方客服", 4, "service"),
    AdKeyword("官方飞投", 5, "service"),
    AdKeyword("官方频道", 3, "service"),
    AdKeyword("飞投", 4, "service"),
    AdKeyword("福利频道", 4, "service"),
    AdKeyword("注册网址", 5, "service"),
    AdKeyword("注册入口", 5, "service"),
    AdKeyword("彩票客服", 5, "service"),
    AdKeyword("彩票入口", 5, "service"),
    AdKeyword("验资", 4, "service"),
    AdKeyword("担保", 3, "service"),
    AdKeyword("点击查验", 4, "service"),
    AdKeyword("钱包官方", 5, "service"),

    # ── Crypto / Wallet / Payment ──
    AdKeyword("NO钱包", 5, "crypto"),
    AdKeyword("WG联名", 5, "crypto"),
    AdKeyword("USDT娱乐", 5, "crypto"),
    AdKeyword("百亿护航", 4, "crypto"),
    AdKeyword("千万担保", 5, "crypto"),
    AdKeyword("重金缔造", 4, "crypto"),

    # ── Calls-to-Action (lower weight) ──
    AdKeyword("点击查看", 2, "cta"),
    AdKeyword("立即注册", 3, "cta"),
    AdKeyword("立即加入", 2, "cta"),
    AdKeyword("立即领取", 3, "cta"),
    AdKeyword("点击领取", 3, "cta"),
    AdKeyword("VIP升级", 3, "cta"),
    AdKeyword("新会员", 2, "promo"),
    AdKeyword("老会员", 2, "promo"),
    AdKeyword("欢迎各位老板", 4, "cta"),
]

AD_SCORE_THRESHOLD = 10

# Known ad/gambling domain patterns
AD_DOMAIN_PATTERNS = [
    r'n9\.com', r'n9cp', r'566676\.vip',
    r'7t\.c', r'7t国际',
    r'\.top/', r'\.vip/', r'\.bet/', r'\.casino/',
    r'no\.com',
]


def _calculate_ad_score(text: str) -> tuple[int, list[str]]:
    """Weighted scoring with category bonuses."""
    score = 0
    matched_categories = set()

    for kw in AD_KEYWORDS:
        if kw.pattern.lower() in text.lower():
            score += kw.weight
            matched_categories.add(kw.category)

    # Cross-category bonus: hitting 3+ categories = almost certainly an ad
    if len(matched_categories) >= 3:
        score += 5

    # Ad domain URLs
    for pattern in AD_DOMAIN_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            score += 4

    # High emoji density + some keyword hits = casino ad style
    emoji_ratio = _emoji_density(text)
    if emoji_ratio > 0.12 and score > 0:
        score += 3

    # Many URLs + relatively short text = link spam
    urls = re.findall(r'https?://\S+', text)
    lines = [l for l in text.strip().split('\n') if l.strip()]
    if len(urls) >= 5 and len(lines) <= 25:
        score += 5

    # Text is mostly emojis and links with very little actual content
    non_emoji_text = re.sub(r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF\u200d\uFE0F]+', '', text)
    non_emoji_text = re.sub(r'https?://\S+', '', non_emoji_text)
    non_emoji_text = re.sub(r'@\w+', '', non_emoji_text)
    if len(non_emoji_text.strip()) < 50 and score > 5:
        score += 3

    return score, list(matched_categories)


def _emoji_density(text: str) -> float:
    """Calculate what fraction of the text is emoji characters."""
    if not text:
        return 0.0
    emoji_pattern = re.compile(
        "[\U0001F300-\U0001F9FF"
        "\U00002600-\U000027BF"
        "\U0000FE00-\U0000FE0F"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\u200d\u2640-\u2642"
        "\u2300-\u23FF\uFE0F]+",
        re.UNICODE
    )
    emojis = emoji_pattern.findall(text)
    emoji_chars = sum(len(e) for e in emojis)
    return emoji_chars / max(len(text), 1)


def is_ad_or_spam(text: str) -> bool:
    """Advanced ad/spam detection using weighted scoring."""
    if not text:
        return False

    score, categories = _calculate_ad_score(text)

    if score >= AD_SCORE_THRESHOLD:
        logger.info(
            f"[FILTER] Ad detected (score: {score}/{AD_SCORE_THRESHOLD}, "
            f"categories: {', '.join(categories)})"
        )
        return True

    return False


# ══════════════════════════════════════════════
#  2. WELCOME / SERVICE MESSAGE DETECTION
# ══════════════════════════════════════════════

WELCOME_PATTERNS = [
    r"欢迎来到",
    r"欢迎加入",
    r"欢迎.*加入.*群",
    r"已加入群组",
    r"加入了群组",
    r"成功加入",
    r"welcome\s+to\b",
    r"\bhas\s+joined\b",
    r"\bjust\s+joined\b",
    r"welcome\s+aboard",
    r"welcome\s+new\s+member",
    r"被邀请加入",
    r"invited\s+to\s+join",
]


def is_welcome_message(text: str) -> bool:
    """Detects welcome/join/service messages (always short)."""
    if not text:
        return False
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

@dataclass(frozen=True)
class FooterPattern:
    pattern: str
    score: int


FOOTER_PATTERNS = [
    # High confidence — almost certainly footer
    FooterPattern(r't\.me/\+?\w+', 10),
    FooterPattern(r'@\w{4,}', 6),
    FooterPattern(r'https?://t\.me/', 10),
    FooterPattern(r'https?://\S+', 4),

    # Chinese footer text
    FooterPattern(r'订阅|频道|群聊|加入群', 7),
    FooterPattern(r'广告|爆料|投稿|报料|報料', 7),
    FooterPattern(r'关注|關注|联系|聯繫', 6),
    FooterPattern(r'加入群组', 8),
    FooterPattern(r'订阅频道', 8),

    # English footer text
    FooterPattern(r'subscribe|channel|follow|contact', 5),

    # Emoji-led promotional lines
    FooterPattern(r'^\s*📣', 8),
    FooterPattern(r'^\s*💬', 7),
    FooterPattern(r'^\s*🔗', 8),
    FooterPattern(r'^\s*📢', 8),
    FooterPattern(r'^\s*😍', 5),
    FooterPattern(r'^\s*👉', 6),
    FooterPattern(r'^\s*📌', 6),
    FooterPattern(r'^\s*🔔', 6),
    FooterPattern(r'^\s*☮', 6),
    FooterPattern(r'^\s*☎', 6),
    FooterPattern(r'^\s*🌐', 6),
    FooterPattern(r'^\s*📲', 6),
    FooterPattern(r'^\s*✅', 4),
    FooterPattern(r'^\s*⬇', 5),
    FooterPattern(r'^\s*↓', 5),
]

FOOTER_LINE_THRESHOLD = 6
MAX_FOOTER_SCAN = 20

# Lines that act as separator between content and footer
SEPARATOR_PATTERNS = [
    r'^[\s]*——+[\s]*$',    # Chinese em-dash separator ——
    r'^[\s]*--+[\s]*$',     # Dashes ---
    r'^[\s]*==+[\s]*$',     # Equals ===
    r'^[\s]*━+[\s]*$',      # Heavy horizontal line
    r'^[\s]*─+[\s]*$',      # Light horizontal line
    r'^[\s]*\*\*+[\s]*$',   # Asterisks ***
]


def _is_separator_line(line: str) -> bool:
    """Check if a line is a content-footer separator."""
    stripped = line.strip()
    if not stripped:
        return False
    for pattern in SEPARATOR_PATTERNS:
        if re.search(pattern, stripped):
            return True
    return False


def _score_footer_line(line: str) -> int:
    """Calculate how likely a line is part of a footer."""
    stripped = line.strip()
    if not stripped:
        return 0

    # Separator lines are definitely footer boundaries
    if _is_separator_line(stripped):
        return 99

    total = 0
    for fp in FOOTER_PATTERNS:
        if re.search(fp.pattern, stripped, re.IGNORECASE):
            total += fp.score

    return total


def _find_footer_boundary(lines: list[str]) -> int:
    """
    Scans from bottom upward to find where footer starts.
    Handles separators (——, ---) as explicit footer markers.
    """
    total_lines = len(lines)
    if total_lines == 0:
        return total_lines

    scan_start = max(0, total_lines - MAX_FOOTER_SCAN)
    footer_start = total_lines
    found_footer_line = False

    for i in range(total_lines - 1, scan_start - 1, -1):
        stripped = lines[i].strip()

        # Separator line — everything below (including this) is footer
        if _is_separator_line(stripped):
            footer_start = i
            found_footer_line = True
            continue

        # Score this line
        score = _score_footer_line(lines[i])

        if score >= FOOTER_LINE_THRESHOLD:
            footer_start = i
            found_footer_line = True
        elif not stripped:
            # Empty line — include if we already found footer below
            if found_footer_line:
                footer_start = i
        else:
            # Non-footer content line
            if found_footer_line:
                break

    return footer_start


def replace_footer(text: str, custom_footer: str) -> str:
    """
    Detects and removes existing footer, appends custom footer.
    Handles various separator styles (——, ---, empty lines).
    """
    if not text:
        return custom_footer.strip()

    lines = text.split('\n')
    footer_boundary = _find_footer_boundary(lines)

    # Content = everything before footer
    content_lines = lines[:footer_boundary]

    # Trim trailing empty lines
    while content_lines and not content_lines[-1].strip():
        content_lines.pop()

    content = '\n'.join(content_lines)

    if content:
        return f"{content}\n\n{custom_footer.strip()}"
    else:
        return custom_footer.strip()


# ══════════════════════════════════════════════
#  4. MAIN ENTRY POINT
# ══════════════════════════════════════════════

def process_message_text(text: str, custom_footer: str) -> str | None:
    """
    Full message processing pipeline:
    1. Ad/spam → None (skip)
    2. Welcome → None (skip)
    3. Footer replace → modified text

    Returns None = skip, str = forward with this text.
    """
    if not text:
        return custom_footer.strip()

    if is_ad_or_spam(text):
        return None

    if is_welcome_message(text):
        return None

    return replace_footer(text, custom_footer)
