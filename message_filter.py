# ============================================
#  Message Filter Engine
#  - Ad/Spam detection (gambling only)
#  - Footer replacement (links + @usernames)
#  - Welcome message skip
# ============================================

import re
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
#  1. AD / SPAM DETECTION
#  Only blocks PURE advertisement posts
#  (gambling, casino, betting — not normal posts)
# ══════════════════════════════════════════════

# High-confidence gambling/casino/platform keywords
AD_KEYWORDS = [
    # Gambling / Casino — very specific
    "彩票入口", "注册就送", "注册网址", "高赔率", "高返水",
    "娱乐城", "真人荷官", "体育博彩", "百家乐", "老虎机",
    "官方客服", "官方飞投", "彩票客服", "福利频道",
    "首存", "笔笔送", "彩金", "特码",
    "NO钱包", "WG联名", "验资", "担保域名",
    # Platform ads (7T, N9 style)
    "注册登入", "极速出款", "安全稳定", "顶级平台",
    "千万担保", "百亿护航", "重金缔造", "钱包官方",
    "惊喜奇遇", "六大版块", "应有尽有",
    "新春纵享", "好运不掉线",
    # Deposit/withdraw
    "充值笔笔送", "夜间充值", "累计存款", "存款赠送",
    "电子狂欢", "赠送", "返水",
    # Service/registration
    "注册入口", "彩票飞投", "客服",
    "飞投", "担保",
    # Domain patterns (specific casino brands)
    "N9.COM", "7T.COM", "N9国际", "7T国际",
]

# Need at least this many keyword matches to block
AD_THRESHOLD = 3

# Known ad domain patterns
AD_DOMAINS = [
    r'n9\.com', r'7t\.com', r'n9cp', r'566676\.vip',
    r'\.vip/', r'\.bet/', r'\.casino/',
]


def _emoji_density(text: str) -> float:
    """What fraction of the text is emoji characters."""
    if not text:
        return 0.0
    emoji_re = re.compile(
        "[\U0001F300-\U0001F9FF"
        "\U00002600-\U000027BF"
        "\U0001FA00-\U0001FAFF"
        "\u200d\u2640-\u2642"
        "\u2300-\u23FF\uFE0F]+", re.UNICODE
    )
    emoji_chars = sum(len(m) for m in emoji_re.findall(text))
    return emoji_chars / max(len(text), 1)


def is_ad_or_spam(text: str) -> bool:
    """
    Returns True ONLY for pure gambling/casino/platform advertisement posts.
    Uses keyword matching + emoji density + domain detection.
    """
    if not text:
        return False

    text_lower = text.lower()

    # Keyword match count
    hits = sum(1 for kw in AD_KEYWORDS if kw.lower() in text_lower)

    if hits >= AD_THRESHOLD:
        logger.info(f"[FILTER] Ad blocked ({hits} keywords matched)")
        return True

    # Ad domain detection (even 1 domain + 1 keyword = ad)
    domain_hit = any(re.search(p, text_lower) for p in AD_DOMAINS)
    if domain_hit and hits >= 1:
        logger.info(f"[FILTER] Ad blocked (ad domain + {hits} keywords)")
        return True

    # High emoji density + at least 1 keyword = likely ad
    if _emoji_density(text) > 0.10 and hits >= 2:
        logger.info(f"[FILTER] Ad blocked (emoji spam + {hits} keywords)")
        return True

    return False


# ══════════════════════════════════════════════
#  2. WELCOME / JOIN MESSAGE DETECTION
# ══════════════════════════════════════════════

WELCOME_PATTERNS = [
    r"欢迎来到",
    r"欢迎加入",
    r"欢迎.*加入.*群",
    r"welcome\s+to\b",
    r"\bhas\s+joined\b",
]


def is_welcome_message(text: str) -> bool:
    """Returns True for auto-generated welcome/join messages (short only)."""
    if not text or len(text) > 200:
        return False

    for pattern in WELCOME_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.info("[FILTER] Welcome message skipped")
            return True

    return False


# ══════════════════════════════════════════════
#  3. FOOTER REPLACEMENT
#  Removes bottom lines with links, @usernames,
#  bare domains, and text sandwiched between them
# ══════════════════════════════════════════════

def _is_link_line(line: str) -> bool:
    """
    A line is a link/footer line if it contains:
    - A t.me link (t.me/xxx) — with or without https:// or inside ()
    - An @username mention (not preceded by alphanumeric = not email)
    - A full URL (https:// or http://)
    - A bare domain (xxx.com, xxx.vip, xxx.top, etc.)
    - A ---- separator line (markdown HR)
    """
    stripped = line.strip()

    if not stripped:
        return False

    # ---- separator (markdown HR / content-footer boundary)
    if re.match(r'^-{3,}\s*$', stripped):
        return True

    # t.me link (with or without https://, with or without parentheses)
    if re.search(r't\.me/\S+', stripped):
        return True

    # @username mention (at least 4 chars, not email)
    if re.search(r'(?<![a-zA-Z0-9])@\w{4,}', stripped):
        return True

    # Full URL
    if re.search(r'https?://\S+', stripped):
        return True

    # Bare domain (xxx.com, xxx.vip, xxx.top, xxx.net, xxx.org, etc.)
    if re.search(r'\b\w+\.(com|vip|top|net|org|info|cc|co|io|me|xyz|bet|casino)\b', stripped, re.IGNORECASE):
        return True

    return False


def replace_footer(text: str, custom_footer: str) -> str:
    """
    Two-pass footer detection:
    Pass 1: Mark all lines with links/@usernames/domains
    Pass 2: From bottom, find contiguous footer block.
            Text lines sandwiched between link lines are also footer.
    """
    if not text:
        return custom_footer.strip()

    lines = text.split('\n')
    total = len(lines)

    # Pass 1: Mark all link lines
    is_link = [_is_link_line(line) for line in lines]

    # Find the last link line
    last_link = -1
    for i in range(total - 1, -1, -1):
        if is_link[i]:
            last_link = i
            break

    # No links found — just append footer
    if last_link == -1:
        return f"{text.rstrip()}\n\n{custom_footer.strip()}"

    # Pass 2: From remaining lines (bottom→up), build footer block.
    # A non-link line is part of footer IF there's a link line within 2 lines below it
    # AND a link line within 2 lines above it (sandwiched).
    # We expand the footer zone from bottom upward.
    footer_zone = [False] * total

    # Start: mark all link lines in the bottom region as footer
    # First, find the contiguous footer block from the bottom
    for i in range(total - 1, -1, -1):
        if is_link[i]:
            footer_zone[i] = True
        elif not lines[i].strip():
            # Empty line — mark as footer if adjacent link lines exist below
            has_link_below = any(footer_zone[j] for j in range(i + 1, min(i + 4, total)))
            if has_link_below:
                footer_zone[i] = True
        else:
            # Non-link, non-empty line
            # Check if sandwiched: link line exists ABOVE and BELOW within range
            has_link_below = any(footer_zone[j] for j in range(i + 1, min(i + 3, total)))
            has_link_above = any(is_link[j] for j in range(max(0, i - 2), i))

            if has_link_below and has_link_above:
                # Sandwiched between link lines — part of footer
                footer_zone[i] = True
            elif has_link_below and not has_link_above:
                # Above the footer block — might be the first non-link line
                # Only include if short (promo text like 关注柬埔寨热点：)
                # Stop if it looks like real content
                break
            else:
                # No links below or too far — real content
                break

    # Find the topmost footer line
    footer_start = total
    for i in range(total):
        if footer_zone[i]:
            footer_start = i
            break

    # No footer found — just append
    if footer_start >= total:
        return f"{text.rstrip()}\n\n{custom_footer.strip()}"

    # Remove empty lines between content and footer
    while footer_start > 0 and not lines[footer_start - 1].strip():
        footer_start -= 1

    # Extract content
    content_lines = lines[:footer_start]
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
    Pipeline:
    1. Ad? → return None (skip)
    2. Welcome? → return None (skip)
    3. Replace footer → return modified text

    None = skip, str = send with this text
    """
    if not text:
        return custom_footer.strip()

    if is_ad_or_spam(text):
        return None

    if is_welcome_message(text):
        return None

    return replace_footer(text, custom_footer)
