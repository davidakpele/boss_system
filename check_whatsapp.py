"""
Run this ON YOUR SERVER (where BOSS is running):
  python check_whatsapp.py

It will diagnose exactly why messages aren't delivering.
"""
import asyncio, httpx

TOKEN    = "EAAUyBQ13A9kBRKB67PwmyZAvKoRQTKL7TyIZAJfj2nI3abw2t9P8I4WzRJzBZAcSDdKeWCr7T2U79CBUuWZCO3m6EmfjUWVII4FLxk9pXDyoUupWQ2pzbkBOllBor7twYNlH3tZCdhhgowAlTIudu9i9YaBoBZC9PjVpHTuwjXWdvw7ALnZBA6aqfwdFK0KDLp0f0ZByZC39IxsSLTiUkPD6JehnPr8U9hBJW6otJxLXDMsgsZAc2BUm2K0Aqyzq4vAhxWOKnLDdx4DF3qZCYHWX3b0"
PHONE_ID = "1082779354917692"
VERSION  = "v21.0"
API_URL  = f"https://graph.facebook.com/{VERSION}/{PHONE_ID}/messages"
HEADERS  = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

async def main():
    async with httpx.AsyncClient(timeout=15) as c:

        # ── 1. Token + Phone status ──────────────────────────────────────────
        print("\n=== TOKEN & PHONE STATUS ===")
        r = await c.get(
            f"https://graph.facebook.com/{VERSION}/{PHONE_ID}",
            params={"fields": "display_phone_number,verified_name,quality_rating,status,name_status"},
            headers=HEADERS
        )
        d = r.json()
        if r.status_code == 200:
            print(f"✅ Token valid")
            print(f"   Number : {d.get('display_phone_number')}")
            print(f"   Name   : {d.get('verified_name')}")
            print(f"   Status : {d.get('status')}")
            print(f"   Quality: {d.get('quality_rating')}")
        else:
            err = d.get('error', {})
            print(f"❌ Token INVALID — {err.get('message')}")
            print("   FIX: Generate new token in Meta dashboard → WhatsApp → API Setup")
            return

        # ── 2. Check if account is in sandbox / dev mode ─────────────────────
        print("\n=== APP MODE ===")
        # Try to send to a dummy number — error code tells us mode
        r2 = await c.post(API_URL, headers=HEADERS, json={
            "messaging_product": "whatsapp",
            "to": "1234567890",  # fake number — we just want the error code
            "type": "text",
            "text": {"body": "test"}
        })
        d2 = r2.json()
        err2 = d2.get("error", {})
        code = err2.get("code")

        if code == 131030:
            print("🔴 APP IS IN DEVELOPMENT MODE")
            print("   This is WHY messages don't deliver.")
            print("   Meta accepts the call but silently drops delivery.")
            print()
            print("   ══ FIX (30 seconds) ══════════════════════════════════")
            print("   1. Go to: https://developers.facebook.com/apps/")
            print("   2. Open your app")
            print("   3. TOP of page: toggle  [Development] → [Live]")
            print("   4. Click 'Switch to Live Mode'")
            print("   5. Done — messages will deliver immediately")
            print("   ═════════════════════════════════════════════════════")
        elif code == 131026:
            print("🟡 APP IS IN LIVE MODE ✅")
            print("   But you're hitting the 24h window rule.")
            print("   The recipient must message YOU first,")
            print("   OR you must use an approved template as the opener.")
        elif code == 190:
            print("❌ Token expired — generate a new one")
        elif "messages" in d2:
            print("✅ APP IS IN LIVE MODE — send worked on dummy number")
        else:
            print(f"Unknown state — raw: {d2}")

asyncio.run(main())