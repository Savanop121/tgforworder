# ============================================
#  Advanced Message Filter Engine v2
#  - Weighted Ad/Spam Scoring
#  - Promotional Link Block Stripping (anywhere in message)
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
    pattern: str
    weight: int
    category: str


AD_KEYWORDS = [
    # ── Gambling / Casino ──
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
    AdKeyword("国际娱乐", 5, "gambling"),

    # ── Registration / Deposit Promos ──
    AdKeyword("注册就送", 5, "promo"),
    AdKeyword("注册登入", 5, "promo"),
    AdKeyword("首存", 5, "promo"),
    AdKeyword("二存", 4, "promo"),
    AdKeyword("三存", 4, "promo"),
    AdKeyword("充值", 3, "promo"),
    AdKeyword("赠送", 3, "promo"),
    AdKeyword("存款", 3, "promo"),
    AdKeyword("笔笔送", 5, "promo"),
    AdKeyword("无上限", 4, "promo"),
    AdKeyword("惊喜奇遇", 3, "promo"),
    AdKeyword("新春", 2, "promo"),
    AdKeyword("极速出款", 5, "promo"),

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
    AdKeyword("点击查验", 4, "service"),

    # ── Crypto / Wallet Scams ──
    AdKeyword("NO钱包", 5, "crypto"),
    AdKeyword("WG联名", 5, "crypto"),
    AdKeyword("USDT娱乐", 5, "crypto"),

    # ── Generic CTA ──
    AdKeyword("点击查看", 2, "cta"),
    AdKeyword("立即注册", 3, "cta"),
    AdKeyword("立即加入", 2, "cta"),
    AdKeyword("立即领取", 3, "cta"),
    AdKeyword("点击领取", 3, "cta"),
    AdKeyword("VIP升级", 3, "cta"),
    AdKeyword("新会员", 2, "promo"),
    AdKeyword("老会员", 2, "promo"),
    AdKeyword("优惠活动", 3, "promo"),
    AdKeyword("安全稳定", 2, "promo"),
    AdKeyword("顶级平台", 3, "promo"),
    AdKeyword("重金缔造", 4, "promo"),
    AdKeyword("百亿护航", 4, "promo"),
    AdKeyword("千万担保", 5, "promo"),
]

AD_SCORE_THRESHOLD = 10

AD_DOMAIN_PATTERNS = [
    r'n9\.com', r'n9cp', r'566676\.vip', r'7t\.c',
    r'\.top/', r'\.vip/', r'\.bet/', r'\.casino/',
]


def _calculate_ad_score(text: str) -> tuple[int, list[str]]:
    """Weighted spam scoring with category bonuses."""
    score = 0
    matched_categories = set()

    for kw in AD_KEYWORDS:
        if kw.pattern.lower() in text.lower():
            score += kw.weight
            matched_categories.add(kw.category)

    # Cross-category bonus
    if len(matched_categories) >= 3:
        score += 5

    # Ad domain URLs
    for pattern in AD_DOMAIN_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            score += 4

    # High emoji density + some ad signals
    emoji_count = len(re.findall(
        r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FAFF]',
        text
    ))
    text_len = max(len(text), 1)
    if (emoji_count / text_len) > 0.1 and score > 0:
        score += 3

    # Lots of URLs in short message
    urls = re.findall(r'https?://\S+', text)
    lines = [l for l in text.strip().split('\n') if l.strip()]
    if len(urls) >= 5 and len(lines) <= 25:
        score += 5

    return score, list(matched_categories)


def is_ad_or_spam(text: str) -> bool:
    """Returns True if message is ad/spam → should be skipped."""
    if not text:
        return False
    score, categories = _calculate_ad_score(text)
    if score >= AD_SCORE_THRESHOLD:
        logger.info(
            f"[FILTER] Ad detected (score: {score}/{AD_SCORE_THRESHOLD}, "
            f"cats: {', '.join(categories)})"
        )
        return True
    return False


def is_ad_or_spam_with_score(text: str) -> tuple[bool, int, list[str]]:
    """
    Returns (is_ad, score, categories).
    Used by OCR detector for detailed logging.
    """
    if not text:
        return False, 0, []
    score, categories = _calculate_ad_score(text)
    is_ad = score >= AD_SCORE_THRESHOLD
    return is_ad, score, categories


# ══════════════════════════════════════════════
#  2. WELCOME / SERVICE MESSAGE DETECTION
# ══════════════════════════════════════════════

WELCOME_PATTERNS = [
    r"欢迎来到", r"欢迎加入", r"欢迎.*加入.*群",
    r"已加入群组", r"加入了群组", r"成功加入",
    r"welcome\s+to\b", r"\bhas\s+joined\b",
    r"\bjust\s+joined\b", r"welcome\s+aboard",
    r"被邀请加入", r"invited\s+to\s+join",
]


def is_welcome_message(text: str) -> bool:
    """Detects welcome/join messages (short auto-generated notifications)."""
    if not text or len(text) > 300:
        return False
    for pattern in WELCOME_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.info("[FILTER] Welcome message detected, skipping")
            return True
    return False


# ══════════════════════════════════════════════
#  3. PROMOTIONAL LINK BLOCK STRIPPING
#     Removes blocks of t.me links from ANYWHERE
#     in the message (top, middle, bottom)
# ══════════════════════════════════════════════

def _is_promo_line(line: str) -> bool:
    """
    Check if a line is part of a promotional link block.
    These blocks typically contain:
    - t.me/ links (bare or in markdown)
    - Channel/group names followed by t.me links
    - Emoji-led promotional lines
    - Lines that are just short Chinese text labels for links
    """
    stripped = line.strip()

    if not stripped:
        return False  # Empty lines handled by context

    # Direct t.me link (bare URL)
    if re.search(r'https?://t\.me/\w+', stripped):
        return True

    # Markdown-style link with t.me
    if re.search(r'\(https?://t\.me/\w+\)', stripped):
        return True

    # Line is just a short Chinese label (<=15 chars, no punctuation, no hashtags)
    # These sit between t.me links as labels like "台湾人在柬埔寨"
    if (len(stripped) <= 15 and
            re.match(r'^[\u4e00-\u9fff\w\s]+$', stripped) and
            not stripped.startswith('#')):
        return True  # Will be validated by context

    # Lines starting with promotion emojis
    if re.match(r'^[📣💬🔗📢🔔☮️☎️👉📌🌐📲⬇️↓🚀✅🤝🔥⚡️💝🎯]', stripped):
        return True

    # Lines with @username mentions that look promotional
    if re.match(r'^.*[:：]\s*@\w{3,}', stripped):
        return True

    # "---" separator
    if re.match(r'^-{2,}$', stripped):
        return True

    return False


def _strip_promo_blocks(text: str) -> str:
    """
    Removes all promotional link blocks from the message.
    A promo block = 3+ consecutive promo lines (with optional empty lines between them).

    Logic:
    1. Scan all lines, mark each as promo or content
    2. Find contiguous blocks of promo lines (allowing empty gaps)
    3. If a block has 3+ promo lines → remove it entirely
    4. Short Chinese labels only count as promo if adjacent to t.me link lines
    """
    lines = text.split('\n')
    n = len(lines)

    # Phase 1: Score each line
    line_info = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        has_tme = bool(re.search(r't\.me/', stripped))
        has_link = bool(re.search(r'https?://\S+', stripped))
        has_markdown_link = bool(re.search(r'\(https?://\S+\)', stripped))
        is_emoji_promo = bool(re.match(r'^[📣💬🔗📢🔔☮️☎️👉📌🌐📲⬇️↓🚀✅🤝🔥⚡️💝🎯]', stripped))
        is_at_mention_line = bool(re.match(r'^.*[:：]\s*@\w{3,}', stripped))
        is_short_label = (
            len(stripped) <= 15 and
            bool(re.match(r'^[\u4e00-\u9fff\w\s]+$', stripped)) and
            not re.search(r'[。！？，、；：]', stripped) and  # Not a real sentence
            not stripped.startswith('#')  # Not a hashtag/topic
        )
        is_separator = bool(re.match(r'^-{2,}$', stripped))
        is_empty = not stripped

        is_strong_promo = has_tme or is_emoji_promo or is_at_mention_line or is_separator
        is_weak_promo = is_short_label or (has_link and not has_tme) or has_markdown_link

        line_info.append({
            'text': line,
            'stripped': stripped,
            'is_empty': is_empty,
            'is_strong_promo': is_strong_promo,
            'is_weak_promo': is_weak_promo,
            'remove': False
        })

    # Phase 2: Find and mark promo blocks
    # A block = contiguous run of strong promo + weak promo + empty lines
    # Block is only removed if it has 3+ strong promo lines (t.me links, emoji promo, etc.)
    # This prevents short news content from being eaten
    i = 0
    while i < n:
        info = line_info[i]

        if info['is_strong_promo']:
            # Potential block start — scan forward
            block_start = i
            block_end = i
            strong_count = 1
            consecutive_weak_only = 0  # Track how many non-strong lines we've absorbed

            j = i + 1
            gap = 0
            while j < n:
                jinfo = line_info[j]
                if jinfo['is_empty']:
                    gap += 1
                    if gap > 2:
                        break
                    j += 1
                    continue
                elif jinfo['is_strong_promo']:
                    strong_count += 1
                    block_end = j
                    gap = 0
                    consecutive_weak_only = 0
                    j += 1
                elif jinfo['is_weak_promo']:
                    # Only absorb weak lines if we haven't gone too far without a strong line
                    consecutive_weak_only += 1
                    if consecutive_weak_only > 2:
                        break  # Too many weak-only lines = probably real content
                    block_end = j
                    gap = 0
                    j += 1
                else:
                    break

            # Only remove if the block has enough strong promo signals
            if strong_count >= 2:
                # Include surrounding empty lines
                while block_end + 1 < n and line_info[block_end + 1]['is_empty']:
                    block_end += 1
                while block_start > 0 and line_info[block_start - 1]['is_empty']:
                    block_start -= 1

                for idx in range(block_start, block_end + 1):
                    line_info[idx]['remove'] = True

            i = block_end + 1
        else:
            i += 1

    # Phase 3: Build result with non-removed lines
    result_lines = [info['text'] for info in line_info if not info['remove']]

    # Clean up multiple consecutive blank lines
    cleaned = []
    prev_blank = False
    for line in result_lines:
        if not line.strip():
            if not prev_blank:
                cleaned.append(line)
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    # Trim leading/trailing blanks
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    return '\n'.join(cleaned)


# ══════════════════════════════════════════════
#  4. SMART FOOTER DETECTION & REPLACEMENT
# ══════════════════════════════════════════════

@dataclass(frozen=True)
class FooterPattern:
    pattern: str
    score: int


FOOTER_PATTERNS = [
    FooterPattern(r't\.me/\+?\w+', 10),
    FooterPattern(r'@\w{4,}', 6),
    FooterPattern(r'https?://t\.me/', 10),
    FooterPattern(r'https?://\S+', 4),
    FooterPattern(r'订阅|频道|群聊|加入群', 7),
    FooterPattern(r'广告|爆料|投稿|报料|報料', 7),
    FooterPattern(r'关注|關注|联系|聯繫', 6),
    FooterPattern(r'subscribe|channel|follow|contact', 5),
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
    FooterPattern(r'^[\s]*⬇️', 5),
    FooterPattern(r'^[\s]*↓', 5),
    FooterPattern(r'^[\s]*🚀', 6),
]

FOOTER_LINE_THRESHOLD = 6
MAX_FOOTER_SCAN = 15


def _score_footer_line(line: str) -> int:
    stripped = line.strip()
    if not stripped:
        return 0
    # Hashtag/topic lines are content, not footer
    if stripped.startswith('#'):
        return 0
    total = 0
    for fp in FOOTER_PATTERNS:
        if re.search(fp.pattern, stripped, re.IGNORECASE):
            total += fp.score
    return total


def _find_footer_boundary(lines: list[str]) -> int:
    """Scans from bottom upward to find footer start index."""
    total = len(lines)
    if total == 0:
        return total

    scan_start = max(0, total - MAX_FOOTER_SCAN)
    footer_start = total
    found_footer = False

    for i in range(total - 1, scan_start - 1, -1):
        stripped = lines[i].strip()
        if not stripped:
            if found_footer:
                footer_start = i
            continue

        score = _score_footer_line(lines[i])
        if score >= FOOTER_LINE_THRESHOLD:
            footer_start = i
            found_footer = True
        else:
            if found_footer:
                break

    return footer_start


def replace_footer(text: str, custom_footer: str) -> str:
    """Detects/removes existing footer, appends custom footer."""
    if not text:
        return custom_footer.strip()

    lines = text.split('\n')
    boundary = _find_footer_boundary(lines)
    content_lines = lines[:boundary]

    while content_lines and not content_lines[-1].strip():
        content_lines.pop()

    content = '\n'.join(content_lines)
    if content:
        return f"{content}\n\n{custom_footer.strip()}"
    return custom_footer.strip()


# ══════════════════════════════════════════════
#  5. INLINE LINK REMOVAL
#     Removes bare URLs and markdown URLs from
#     content lines (not just promo blocks)
# ══════════════════════════════════════════════

def _remove_inline_links(text: str) -> str:
    """
    Removes standalone URLs and markdown-format links from text.
    - Bare URLs on their own line → remove entire line
    - Markdown links like (https://...) → remove the link part
    - URLs within sentences → remove just the URL
    """
    lines = text.split('\n')
    cleaned = []

    for line in lines:
        stripped = line.strip()

        # Skip lines that are ONLY a URL
        if re.match(r'^https?://\S+$', stripped):
            continue

        # Remove markdown-style links: (https://...)
        line = re.sub(r'\s*\(https?://\S+?\)', '', line)

        # Remove bare URLs within text
        line = re.sub(r'\s*https?://\S+', '', line)

        # Clean up double spaces
        line = re.sub(r'  +', ' ', line)

        cleaned.append(line)

    return '\n'.join(cleaned)


# ══════════════════════════════════════════════
#  6. MAIN PIPELINE
# ══════════════════════════════════════════════

def process_message_text(text: str, custom_footer: str) -> str | None:
    """
    Full message processing pipeline:
    1. Ad/spam check → return None to skip
    2. Welcome message check → return None to skip
    3. Strip promotional link blocks (anywhere in message)
    4. Remove inline links from content
    5. Footer detection & replacement

    Returns None = skip this message entirely
    Returns str  = forward with this modified text
    """
    if not text:
        return custom_footer.strip()

    # Stage 1: Ad/spam detection
    if is_ad_or_spam(text):
        return None

    # Stage 2: Welcome message detection
    if is_welcome_message(text):
        return None

    # Stage 3: Strip promotional link blocks
    text = _strip_promo_blocks(text)

    # Stage 4: Remove inline links from remaining content
    text = _remove_inline_links(text)

    # Stage 5: Footer replacement
    text = replace_footer(text, custom_footer)

    # Final cleanup: remove excessive blank lines
    text = re.sub(r'\n{4,}', '\n\n\n', text)

    return text
