# ============================================
#  Message Filter — Ad Detection, Welcome Skip,
#  Footer Replacement
# ============================================

import re
import logging

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  Ad/Spam Detection
# ──────────────────────────────────────────────

# Gambling/casino/ad keywords (Chinese + common patterns)
AD_KEYWORDS = [
    # Gambling/Casino
    "注册", "充值", "彩票", "赔率", "返水", "赠送", "娱乐城",
    "入口", "客服", "飞投", "福利频道", "注册网址", "担保", "验资",
    "首存", "二存", "三存", "打码", "VIP升级", "彩金",
    "狂欢", "优惠", "老会员", "新会员",
    "官方客服", "官方飞投",
    # Betting patterns
    "特码", "高赔率", "高返水",
    # Wallet/payment scams
    "NO钱包", "WG联名",
    # Generic ad markers
    "点击查看", "立即注册", "立即加入",
]

# Minimum keyword matches to classify as ad
AD_KEYWORD_THRESHOLD = 3


def is_ad_or_spam(text: str) -> bool:
    """
    Returns True if the message is an advertisement/spam.
    Detection: keyword density + URL density for short messages.
    """
    if not text:
        return False

    text_lower = text.lower()

    # Count ad keyword matches
    keyword_hits = sum(1 for kw in AD_KEYWORDS if kw.lower() in text_lower)
    if keyword_hits >= AD_KEYWORD_THRESHOLD:
        logger.info(f"[FILTER] Ad detected: {keyword_hits} keyword hits")
        return True

    # High URL density in short messages (ad pattern)
    urls = re.findall(r'https?://\S+', text)
    lines = [l for l in text.strip().split('\n') if l.strip()]
    if len(urls) >= 4 and len(lines) <= 20:
        logger.info(f"[FILTER] Ad detected: {len(urls)} URLs in {len(lines)} lines")
        return True

    return False


# ──────────────────────────────────────────────
#  Welcome/Join Message Detection
# ──────────────────────────────────────────────

WELCOME_PATTERNS = [
    r"欢迎来到",       # welcome to
    r"欢迎加入",       # welcome join
    r"欢迎.*加入",     # welcome ... join
    r"welcome\s+to",  # English
    r"has\s+joined",  # English join
]


def is_welcome_message(text: str) -> bool:
    """
    Returns True if the message is a welcome/join notification.
    """
    if not text:
        return False

    # Welcome messages are usually short
    if len(text) > 500:
        return False

    for pattern in WELCOME_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.info(f"[FILTER] Welcome message detected, skipping")
            return True

    return False


# ──────────────────────────────────────────────
#  Footer Detection & Replacement
# ──────────────────────────────────────────────

# Patterns that indicate a line is part of a footer
FOOTER_INDICATORS = [
    r't\.me/',                 # Telegram links
    r'@\w{3,}',               # @username mentions (3+ chars)
    r'https?://\S+',          # Any URL
    r'^[\s]*[📣💬😍🔗📢🔔☮️☎️👉📌🌐💰🎯📲✅🔥⚡️💝🤝]+',  # Emoji-starting promo lines
    r'订阅|频道|群聊|广告|爆料|投稿|加入|报料|關注|联系',  # Common footer Chinese words
    r'subscribe|channel|join|contact|follow',  # English footer words
]


def _is_footer_line(line: str) -> bool:
    """Check if a single line looks like part of a footer."""
    stripped = line.strip()

    # Empty lines between footer items count as footer
    if not stripped:
        return True  # Will be validated by context (only if adjacent to other footer lines)

    for pattern in FOOTER_INDICATORS:
        if re.search(pattern, stripped, re.IGNORECASE):
            return True

    return False


def replace_footer(text: str, custom_footer: str) -> str:
    """
    Detects and removes the existing footer from message text,
    then appends the custom footer.

    Logic: Scan from bottom of message upwards. Lines matching footer
    patterns are stripped. Stop when hitting a non-footer line.
    """
    if not text:
        return custom_footer.strip()

    lines = text.split('\n')

    # Scan from bottom to find where footer starts
    footer_start = len(lines)  # default: no footer found
    consecutive_non_footer = 0

    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()

        if not line:
            # Empty line — could be separator between content and footer
            # Only count as footer if we already found footer lines below
            if footer_start < len(lines):
                footer_start = i
            continue

        if _is_footer_line(lines[i]):
            footer_start = i
            consecutive_non_footer = 0
        else:
            consecutive_non_footer += 1
            # If we hit 2+ consecutive non-footer lines, stop scanning
            if consecutive_non_footer >= 2:
                break

    # Keep only content lines (before footer)
    content_lines = lines[:footer_start]

    # Remove trailing empty lines from content
    while content_lines and not content_lines[-1].strip():
        content_lines.pop()

    # Build final message: content + separator + custom footer
    content = '\n'.join(content_lines)

    if content:
        return f"{content}\n\n{custom_footer.strip()}"
    else:
        return custom_footer.strip()


def process_message_text(text: str, custom_footer: str) -> str | None:
    """
    Main entry point for message text processing.
    Returns None if message should be skipped (ad/welcome).
    Returns modified text with footer replaced otherwise.
    """
    if not text:
        return ""

    # Check if ad/spam → skip
    if is_ad_or_spam(text):
        return None

    # Check if welcome message → skip
    if is_welcome_message(text):
        return None

    # Replace footer
    return replace_footer(text, custom_footer)
