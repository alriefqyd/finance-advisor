"""
Mini webhook server — terima POST dari Google Apps Script
dan forward ke handler bot.
Jalan paralel dengan Telegram bot di port 8080.
"""
import os
import json
import hashlib
import hmac
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "ganti_dengan_secret_kamu")

async def handle_email_webhook(request: web.Request) -> web.Response:
    """Endpoint: POST /webhook/email"""
    try:
        # Verifikasi secret
        auth = request.headers.get("X-Webhook-Secret", "")
        if auth != WEBHOOK_SECRET:
            logger.warning("Webhook: invalid secret")
            return web.Response(status=401, text="Unauthorized")

        data = await request.json()
        subject = data.get("subject", "")
        body    = data.get("body", "")
        sender  = data.get("sender", "")

        if not subject:
            return web.Response(status=400, text="Missing subject")

        # Parse email
        from app.email_parser import process_incoming_email
        parsed = process_incoming_email(subject, body, sender)

        if not parsed:
            return web.json_response({"status": "ignored", "reason": "not a transaction"})

        # Simpan ke queue untuk diproses bot
        # Bot akan ambil dari sini via get_pending_emails()
        _email_queue.append(parsed)
        logger.info(f"Email queued: {parsed.get('description')} Rp{parsed.get('amount',0):,.0f}")

        return web.json_response({"status": "queued", "description": parsed.get("description")})

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.Response(status=500, text=str(e))


async def health_check(request: web.Request) -> web.Response:
    return web.Response(text="Fin Bot OK")


# ── In-memory queue ────────────────────────────────────
_email_queue: list = []

def get_pending_emails() -> list:
    """Ambil semua email pending dan kosongkan queue."""
    pending = _email_queue.copy()
    _email_queue.clear()
    return pending


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/",               health_check)
    app.router.add_post("/webhook/email", handle_email_webhook)
    return app
