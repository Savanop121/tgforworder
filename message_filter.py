# ============================================
#  Message Filter Engine
#  - Ad/Spam detection (gambling only)
#  - Footer replacement (links + @usernames only)
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

# High-confidence gambling/casino keywords
AD_KEYWORDS = [
    # Gambling / Casino — very specific
    "彩票入口", "注册就送", "注册网址", "高赔率", "高返水",
    "娱乐城", "真人荷官", "体育博彩", "百家乐", "老虎机",
    "官方客服", "官方飞投", "彩票客服", "福利频道",
    "首存", "笔笔送", "彩金", "特码",
    "NO钱包", "WG联名", "验资", "担保域名",
]

# Need at least this many keyword matches to block
AD_THRESHOLD = 3


def is_ad_or_spam(text: str) -> bool:
    """
    Returns True ONLY for pure gambling/casino advertisement posts.
    Normal posts with a few promotional words will NOT be blocked.
    """
    if not text:
        return False

    hits = sum(1 for kw in AD_KEYWORDS if kw in text)

    if hits >= AD_THRESHOLD:
        logger.info(f"[FILTER] Ad blocked ({hits} gambling keywords found)")
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
#  Conservative: only removes bottom lines that
#  contain t.me links or @username mentions
# ══════════════════════════════════════════════

def _is_footer_line(line: str) -> bool:
    """
    A line is a footer line ONLY if it contains:
    - A t.me link (t.me/xxx)
    - An @username mention (@xxxx with 4+ chars)
    - A plain URL (https://...)
    """
    stripped = line.strip()

    # Empty line — decided by context (adjacent to other footer lines)
    if not stripped:
        return False

    # t.me link (with or without https://)
    if re.search(r't\.me/\S+', stripped):
        return True

    # @username mention (at least 4 chars after @)
    if re.search(r'@\w{4,}', stripped):
        return True

    # Plain URL (https:// or http://)
    if re.search(r'https?://\S+', stripped):
        return True

    return False


def replace_footer(text: str, custom_footer: str) -> str:
    """
    Scans from bottom of message upward.
    Removes ONLY lines that contain t.me links, @usernames, or URLs.
    Lines without links (even promo text) are kept as-is.
    Empty lines between removed footer lines are also cleaned up.
    """
    if not text:
        return custom_footer.strip()

    lines = text.split('\n')
    total = len(lines)

    # Scan from bottom — remove lines with links/@usernames
    footer_start = total

    for i in range(total - 1, -1, -1):
        stripped = lines[i].strip()

        if not stripped:
            # Empty line — keep scanning (might be between footer lines)
            continue
        elif _is_footer_line(lines[i]):
            # Has link or @username — this is footer
            footer_start = i
        else:
            # No link or @username — stop, this is content
            break

    # No footer found — just append
    if footer_start >= total:
        return f"{text.rstrip()}\n\n{custom_footer.strip()}"

    # Also remove empty lines between content and footer
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
