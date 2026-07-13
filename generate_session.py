"""
Run this script to generate a new Telethon session file.
It will ask for your phone number and OTP code.
After login, the session file will be created.
"""
import asyncio
from telethon import TelegramClient
from config import API_ID, API_HASH, SESSION_NAME

async def main():
    print("=" * 50)
    print("  Generate New Telethon Session")
    print("=" * 50)
    print()
    
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()
    
    me = await client.get_me()
    print(f"\n✅ Login successful! Logged in as: {me.first_name} (@{me.username})")
    print(f"✅ Session file created: {SESSION_NAME}.session")
    print("\nNow push this session file to git and redeploy on Railway.")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
