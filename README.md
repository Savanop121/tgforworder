# Telegram Auto Forwarder & Manager Bot

A powerful Telegram auto-forwarding script that listens to messages from specific source channels, processes them through an advanced filtering engine, and forwards them to a destination channel. It comes with a built-in Telegram Admin Bot to manage settings and channels on the go.

## 🚀 Features

- **Auto Forwarding:** Forwards text, images, videos, and documents seamlessly.
- **Admin Bot Control:** Manage your source and destination channels via a Telegram bot interface.
- **Advanced Message Filtering (`message_filter.py`):**
  - **Smart Footer Detection:** Automatically detects and replaces the source channel's footer with your custom footer.
  - **Ad & Spam Scoring:** Weighted spam scoring to ignore promotional messages.
  - **Link Stripping:** Removes promotional links while keeping the main content intact.
- **Persistent Storage:** Uses MongoDB to store channel configurations and settings.
- **Session Management:** Saves Telethon sessions so you don't have to log in repeatedly.

## 📋 Prerequisites

- Python 3.9+
- A Telegram API ID and Hash (Get it from [my.telegram.org](https://my.telegram.org))
- A Bot Token (Get it from [@BotFather](https://t.me/BotFather))
- A MongoDB Cluster (e.g., MongoDB Atlas Free Tier)

## ⚙️ Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/wdw03/frowwording.git
   cd frowwording
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure the script:**
   Open `config.py` and update the following variables:
   - `API_ID` & `API_HASH`
   - `BOT_TOKEN`
   - `MONGO_URI`
   - `ADMIN_IDS` (Add your Telegram User ID here so the bot responds to you)
   - `CUSTOM_FOOTER` (The footer text appended to forwarded messages)

## ▶️ Running the Bot

Run the main script. It will prompt you to log into your Telegram account the first time to create the `.session` file.

```bash
python main.py
```

*Note: The script runs both the Telethon Userbot (for forwarding) and the Admin Bot concurrently in the background.*

## 🤖 Admin Bot Commands

Send these commands directly to your Bot on Telegram:
- `/start` - Open the admin panel (Add/Remove channels, manage settings)
- `/myid` - View your Telegram ID (Useful for adding to `config.py` for admin access)
- `/cancel` - Cancel the current action

## ⚠️ Security Note
If you are pushing this code to a public repository, make sure your `.session` file is added to `.gitignore`. It contains your Telegram account's active login session.
