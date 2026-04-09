"""
Run this standalone script to test your WhatsApp config OUTSIDE of BOSS.
Usage:
  python whatsapp_send_test.py

It will tell you exactly what is wrong.
"""
import asyncio
import httpx

# ── Paste your values here ────────────────────────────────────────────────────
ACCESS_TOKEN     = ""   # your current token
PHONE_NUMBER_ID  = "1082779354917692"
API_VERSION      = "v21.0"
RECIPIENT_NUMBER = "2349065988804"   # e.g. "2349065988804"  (no + no spaces)
# ─────────────────────────────────────────────────────────────────────────────

API_URL = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}/messages"


async def test_token():
    print("\n=== 1. Checking token validity ===")
    url = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}"
    async with httpx.AsyncClient() as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
        d = r.json()
        if r.status_code == 200:
            print(f"Token valid — Phone: {d.get('display_phone_number')} | Status: {d.get('quality_rating')}")
        else:
            print(f"Token INVALID: {d.get('error', {}).get('message')}")
            return False
    return True


async def test_template_send():
    """Use hello_world template — works even with sandbox restrictions."""
    print("\n=== 2. Sending hello_world template ===")
    payload = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_NUMBER,
        "type": "template",
        "template": {"name": "hello_world", "language": {"code": "en_US"}},
    }
    async with httpx.AsyncClient() as c:
        r = await c.post(
            API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
        )
        d = r.json()
        if r.status_code == 200 and "messages" in d:
            print(f"Template sent! Message ID: {d['messages'][0]['id']}")
            print("   → Check if you received 'Hello World' on WhatsApp")
        else:
            err = d.get("error", d)
            code = err.get("code") if isinstance(err, dict) else "?"
            msg  = err.get("message") if isinstance(err, dict) else str(err)
            print(f"❌ Template send FAILED (code {code}): {msg}")
            if code == 131030:
                print("\n  CAUSE: Your number is NOT in the test recipient list.")
                print("   FIX:")
                print("   1. Go to: https://developers.facebook.com/apps/")
                print("   2. Your App → WhatsApp → API Setup")
                print("   3. Under 'To:' dropdown → click 'Manage phone number list'")
                print(f"   4. Add +{RECIPIENT_NUMBER}")
                print("   5. Meta will send a verification code to that WhatsApp")
                print("   6. Enter the code to confirm")
            elif code == 190:
                print("\n  CAUSE: Access token is expired.")
                print("   FIX: Generate a new token in Meta dashboard → WhatsApp → API Setup")


async def test_freeform_send():
    """Send a plain text message — only works after recipient opts in."""
    print("\n=== 3. Sending freeform text message ===")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": RECIPIENT_NUMBER,
        "type": "text",
        "text": {"preview_url": False, "body": "Test from BOSS System 🤖"},
    }
    async with httpx.AsyncClient() as c:
        r = await c.post(
            API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
        )
        d = r.json()
        if r.status_code == 200 and "messages" in d:
            print(f"Freeform sent! Message ID: {d['messages'][0]['id']}")
        else:
            err = d.get("error", d)
            code = err.get("code") if isinstance(err, dict) else "?"
            msg  = err.get("message") if isinstance(err, dict) else str(err)
            print(f"Freeform send FAILED (code {code}): {msg}")
            if code == 131026:
                print("\n  CAUSE: You can only send freeform messages AFTER the recipient")
                print("   messages YOU first (or within a 24-hour conversation window).")
                print("   FIX: Use hello_world template first (test 2 above), then have")
                print("   the recipient reply to you. After that, freeform works for 24h.")


async def main():
    print("WhatsApp BOSS Diagnostic Tool")
    print("=" * 40)

    if not ACCESS_TOKEN:
        print("ACCESS_TOKEN is empty — paste your token at the top of this file")
        return
    if not RECIPIENT_NUMBER:
        print("RECIPIENT_NUMBER is empty — paste the number to test with")
        return

    token_ok = await test_token()
    if not token_ok:
        return

    await test_template_send()
    await test_freeform_send()

    print("\n=== Summary ===")
    print("For messages to be RECEIVED on WhatsApp in test mode:")
    print("1. Token must be valid (test 1)")
    print("2. Recipient must be in allowed list (Meta dashboard)")
    print("3. For freeform text: recipient must have messaged you first")
    print("4. Use hello_world template for first contact")

asyncio.run(main())