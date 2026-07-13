# ============================================
#  OCR Ad Detector — Image se Text Nikalo + Ad Check
#  Uses Tesseract OCR (offline, no API needed)
#  Integrated with existing keyword-based ad filter
# ============================================

import hashlib
import logging
from collections import OrderedDict
from io import BytesIO

try:
    from PIL import Image, ImageEnhance, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

from config import OCR_AD_DETECTION, OCR_LANGUAGES, OCR_CACHE_SIZE
from message_filter import is_ad_or_spam_with_score

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  LRU Cache — Same image dobara aaye toh skip OCR
# ──────────────────────────────────────────────

class _LRUCache:
    """Simple LRU cache using OrderedDict."""

    def __init__(self, max_size: int = 200):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size

    def get(self, key: str):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, value):
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
        self._cache[key] = value

    def __len__(self):
        return len(self._cache)


_ocr_cache = _LRUCache(max_size=OCR_CACHE_SIZE)


def _check_dependencies() -> bool:
    """Check if OCR dependencies are available."""
    if not PIL_AVAILABLE:
        logger.warning("[OCR] Pillow not installed. OCR ad detection disabled.")
        return False
    if not TESSERACT_AVAILABLE:
        logger.warning("[OCR] pytesseract not installed. OCR ad detection disabled.")
        return False
    # Quick check if tesseract binary exists
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        logger.warning(
            "[OCR] Tesseract binary not found. "
            "Install tesseract-ocr or set pytesseract.pytesseract.tesseract_cmd"
        )
        return False


# Module-level dependency check (runs once at import)
_dependencies_ok: bool | None = None


def _ensure_dependencies() -> bool:
    """Lazy dependency check — runs once and caches result."""
    global _dependencies_ok
    if _dependencies_ok is None:
        _dependencies_ok = _check_dependencies()
        if _dependencies_ok:
            logger.info("[OCR] Tesseract OCR initialized successfully")
        else:
            logger.warning("[OCR] OCR ad detection will be disabled")
    return _dependencies_ok


# ──────────────────────────────────────────────
#  Image Preprocessing — Better OCR Accuracy
# ──────────────────────────────────────────────

def _preprocess_image(img: "Image.Image") -> "Image.Image":
    """
    Preprocess image for better OCR accuracy:
    1. Convert to RGB (handle RGBA/palette images)
    2. Resize small images (min 800px width for better text recognition)
    3. Convert to grayscale
    4. Enhance contrast
    5. Sharpen
    """
    # Step 1: Ensure RGB mode
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Step 2: Resize if too small (text hard to read in tiny images)
    width, height = img.size
    if width < 800:
        scale = 800 / width
        new_size = (int(width * scale), int(height * scale))
        img = img.resize(new_size, Image.LANCZOS)

    # Step 3: Grayscale
    img = img.convert("L")

    # Step 4: Enhance contrast
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.8)

    # Step 5: Sharpen
    img = img.filter(ImageFilter.SHARPEN)

    return img


# ──────────────────────────────────────────────
#  OCR Text Extraction
# ──────────────────────────────────────────────

def _extract_text(img: "Image.Image", languages: str = None) -> str:
    """
    Extract text from image using Tesseract OCR.
    Tries specified languages, falls back to English only if needed.
    """
    if languages is None:
        languages = OCR_LANGUAGES

    try:
        # Try with all configured languages
        text = pytesseract.image_to_string(
            img,
            lang=languages,
            config="--psm 6"  # Assume uniform block of text
        )
        return text.strip()
    except pytesseract.TesseractError as e:
        # Language pack not installed — try English only
        lang_error = "Failed loading language" in str(e) or "Tesseract" in str(e)
        if lang_error and languages != "eng":
            logger.warning(
                f"[OCR] Language pack error ({languages}), falling back to English only"
            )
            try:
                text = pytesseract.image_to_string(
                    img,
                    lang="eng",
                    config="--psm 6"
                )
                return text.strip()
            except Exception as e2:
                logger.error(f"[OCR] English fallback also failed: {e2}")
                return ""
        logger.error(f"[OCR] Tesseract error: {e}")
        return ""
    except Exception as e:
        logger.error(f"[OCR] Unexpected error during text extraction: {e}")
        return ""


# ──────────────────────────────────────────────
#  Image Hash — Cache key generation
# ──────────────────────────────────────────────

def _compute_image_hash(image_bytes: bytes) -> str:
    """Compute MD5 hash of image bytes for cache lookup."""
    return hashlib.md5(image_bytes).hexdigest()


# ──────────────────────────────────────────────
#  Main API — Is This Image An Ad?
# ──────────────────────────────────────────────

def is_image_ad(image_bytes: bytes) -> tuple[bool, str]:
    """
    Main function — checks if an image contains ad content.

    Flow:
    1. Check if OCR is enabled and dependencies available
    2. Check cache (same image seen before?)
    3. Preprocess image
    4. Extract text via OCR
    5. Run extracted text through keyword ad filter
    6. Cache and return result

    Returns: (is_ad: bool, reason: str)
        - is_ad = True → image has ad content, skip forwarding
        - is_ad = False → image is clean, forward it
        - reason = human-readable explanation
    """
    # Check if OCR detection is enabled
    if not OCR_AD_DETECTION:
        return False, "OCR detection disabled"

    # Check dependencies
    if not _ensure_dependencies():
        return False, "OCR dependencies not available"

    # Check cache
    img_hash = _compute_image_hash(image_bytes)
    cached = _ocr_cache.get(img_hash)
    if cached is not None:
        logger.debug(f"[OCR] Cache hit for image {img_hash[:8]}")
        return cached

    try:
        # Open image
        img = Image.open(BytesIO(image_bytes))

        # Skip very small images (icons, emojis, stickers)
        width, height = img.size
        if width < 100 or height < 100:
            result = (False, "Image too small for OCR")
            _ocr_cache.put(img_hash, result)
            return result

        # Preprocess for better OCR
        processed_img = _preprocess_image(img)

        # Extract text
        extracted_text = _extract_text(processed_img)

        if not extracted_text or len(extracted_text.strip()) < 5:
            # No meaningful text found in image
            result = (False, "No text found in image")
            _ocr_cache.put(img_hash, result)
            return result

        # Run through keyword ad filter
        is_ad, score, categories = is_ad_or_spam_with_score(extracted_text)

        if is_ad:
            reason = (
                f"OCR ad detected (score: {score}, "
                f"categories: {', '.join(categories)}, "
                f"text: {extracted_text[:100]}...)"
            )
            logger.info(f"[OCR-FILTER] {reason}")
            result = (True, reason)
        else:
            result = (False, f"OCR clean (score: {score}, text length: {len(extracted_text)})")

        # Cache result
        _ocr_cache.put(img_hash, result)
        return result

    except Exception as e:
        logger.error(f"[OCR] Error processing image: {e}")
        # On error, don't block — let the message through
        return False, f"OCR error: {e}"


def is_image_ad_from_bytesio(media_bytesio: BytesIO) -> tuple[bool, str]:
    """
    Convenience wrapper — accepts BytesIO (already downloaded media).
    Reads bytes without consuming the stream (resets position after).
    """
    original_pos = media_bytesio.tell()
    media_bytesio.seek(0)
    image_bytes = media_bytesio.read()
    media_bytesio.seek(original_pos)  # Reset so caller can still use it

    return is_image_ad(image_bytes)


# ──────────────────────────────────────────────
#  Status / Debug
# ──────────────────────────────────────────────

def get_ocr_status() -> dict:
    """Returns OCR system status — useful for admin bot /status command."""
    return {
        "enabled": OCR_AD_DETECTION,
        "dependencies_ok": _dependencies_ok,
        "pillow_available": PIL_AVAILABLE,
        "tesseract_available": TESSERACT_AVAILABLE,
        "languages": OCR_LANGUAGES,
        "cache_size": len(_ocr_cache),
        "cache_max": OCR_CACHE_SIZE,
    }
