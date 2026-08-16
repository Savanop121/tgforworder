# ============================================
#  Telegram Forwarding Script — Configuration
# ============================================

# Telegram API credentials (from my.telegram.org)
API_ID = 31527593
API_HASH = "dfbc5c90fbcd64a706c2b2ba6419f494"

# Bot token (from @BotFather)
BOT_TOKEN = "8664203521:AAE14Xx3oZPxcZU5yX3wUNciLZxqUdWP8Io"

# MongoDB connection
MONGO_URI = "mongodb+srv://lovetrr:ssgsggsgssg@tgforwirding.cqnncrg.mongodb.net/"
DB_NAME = "tg_forwarder"

# Session file name (Telethon session)
SESSION_NAME = "forwarder_session"

# Admin Telegram user IDs — only these users can use bot commands
# Run the script first, send /myid in bot, then put your ID here
ADMIN_IDS = [6009176071, 7780348576]

# Channel list refresh interval (seconds)
CHANNEL_REFRESH_INTERVAL = 30

# Custom footer — replaces source channel footer on every forwarded message
CUSTOM_FOOTER = """🌴 柬埔寨 420：@greenliving42
🍂雪茄探索 : @HiddenLeafKH"""

# OCR Ad Detection Settings
OCR_AD_DETECTION = True                       # True = Image OCR check ON, False = OFF
OCR_LANGUAGES = "chi_sim+chi_tra+eng"         # Chinese Simplified + Traditional + English
OCR_CACHE_SIZE = 200                          # Kitni images ka result cache mein rakhna
