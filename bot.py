import os
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from dotenv import load_dotenv

load_dotenv()

from app.database import (
    init_db, upsert_user,
    add_transaction, get_transactions, get_summary,
    set_budget, get_budgets, get_budget_usage,
    add_bill, get_bills
)
from app.advisor import parse_transaction, get_advice, ask_claude

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Whitelist: isi dengan Telegram user ID anggota keluarga (string)
ALLOWED_USERS = set(os.getenv("ALLOWED_USER_IDS", "").split(","))


# ── Helpers ────────────────────────────────────────────
def allowed(update: Update) -> bool:
    uid = str(update.effective_user.id)
    if not ALLOWED_USERS or ALLOWED_USERS == {""}:
        return True  # Jika kosong, semua diizinkan (mode dev)
    return uid in ALLOWED_USERS

def fmt_rp(amount: float) -> str:
    return f"Rp{amount:,.0f}".replace(",", ".")

def current_month() -> str:
    return datetime.now().strftime("%Y-%m")


# ── Command Handlers ───────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        await update.message.reply_text("⛔ Maaf, kamu tidak terdaftar.")
        return

    user = update.effective_user
    upsert_user(str(user.id), user.first_name)

    keyboard = [
        ["📊 Laporan Bulan Ini", "💰 Sisa Budget"],
        ["📋 Daftar Tagihan",    "❓ Bantuan"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        f"👋 Halo *{user.first_name}*! Aku *Fin*, asisten keuangan keluargamu.\n\n"
        "Kamu bisa:\n"
        "• Catat transaksi: _\"beli bensin 50rb\"_\n"
        "• Tanya laporan: _\"laporan bulan ini\"_\n"
        "• Minta saran: _\"boleh beli HP baru?\"_\n"
        "• Set budget: /budget makan 1500000\n"
        "• Tambah tagihan: /tagihan PLN 500000 20\n\n"
        "Ketik /help untuk panduan lengkap.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Panduan Fin*\n\n"
        "*Catat Transaksi (chat natural):*\n"
        "• _\"beli makan siang 35rb\"_\n"
        "• _\"terima gaji 8 juta\"_\n"
        "• _\"transfer ke tabungan 500rb\"_\n\n"
        "*Perintah:*\n"
        "/laporan — Ringkasan bulan ini\n"
        "/transaksi — 10 transaksi terakhir\n"
        "/budget [kategori] [limit] — Set budget\n"
        "/tagihan [nama] [jumlah] [tgl] — Tambah tagihan\n"
        "/cekbudget — Status semua budget\n"
        "/tagihan\\_list — Daftar tagihan\n\n"
        "*Tanya Saran:*\n"
        "• _\"boleh beli iPhone bulan ini?\"_\n"
        "• _\"kondisi keuangan aku gimana?\"_\n"
        "• _\"rekomendasi laptop budget 10 juta\"_",
        parse_mode="Markdown"
    )


async def laporan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    uid = str(update.effective_user.id)
    month = current_month()
    summary = get_summary(uid, month)
    budgets = get_budget_usage(uid, month)
    bills = get_bills(uid)

    if not summary:
        await update.message.reply_text(
            "📭 Belum ada transaksi bulan ini.\n"
            "Mulai catat dengan chat natural, contoh: _\"beli makan 25rb\"_",
            parse_mode="Markdown"
        )
        return

    income  = sum(r["total"] for r in summary if r["type"] == "income")
    expense = sum(r["total"] for r in summary if r["type"] == "expense")
    invest  = sum(r["total"] for r in summary if r["type"] == "investment")
    sisa    = income - expense - invest

    bulan_label = datetime.now().strftime("%B %Y")
    text = f"📊 *Laporan {bulan_label}*\n\n"
    text += f"💚 Pemasukan  : *{fmt_rp(income)}*\n"
    text += f"❤️ Pengeluaran: *{fmt_rp(expense)}*\n"
    text += f"💙 Investasi  : *{fmt_rp(invest)}*\n"
    text += f"⚡ Sisa       : *{fmt_rp(sisa)}*\n"

    if expense:
        text += "\n*Pengeluaran per Kategori:*\n"
        for r in sorted(summary, key=lambda x: -x["total"]):
            if r["type"] == "expense":
                text += f"  • {r['category']}: {fmt_rp(r['total'])}\n"

    if budgets:
        text += "\n*Status Budget:*\n"
        for b in budgets:
            pct = (b["spent"] / b["limit_amount"] * 100) if b["limit_amount"] else 0
            bar = "🟢" if pct <= 60 else ("🟡" if pct <= 85 else "🔴")
            text += f"  {bar} {b['category']}: {fmt_rp(b['spent'])} / {fmt_rp(b['limit_amount'])} ({pct:.0f}%)\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def transaksi_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    uid = str(update.effective_user.id)
    rows = get_transactions(uid, limit=10)

    if not rows:
        await update.message.reply_text("Belum ada transaksi tercatat.")
        return

    emoji = {"income": "💚", "expense": "❤️", "investment": "💙"}
    text = "📋 *10 Transaksi Terakhir*\n\n"
    for r in rows:
        e = emoji.get(r["type"], "•")
        text += f"{e} {r['date']} | *{fmt_rp(r['amount'])}* — {r['description']} _({r['category']})_\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def set_budget_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Usage: /budget makan 1500000"""
    if not allowed(update): return
    uid = str(update.effective_user.id)
    args = ctx.args

    if len(args) < 2:
        await update.message.reply_text(
            "Format: /budget [kategori] [jumlah]\n"
            "Contoh: /budget makan 1500000"
        )
        return

    category = args[0].lower()
    try:
        limit = float(args[1].replace(".", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("Jumlah tidak valid.")
        return

    set_budget(uid, category, limit)
    await update.message.reply_text(
        f"✅ Budget *{category}* diset ke *{fmt_rp(limit)}/bulan*",
        parse_mode="Markdown"
    )


async def cek_budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    uid = str(update.effective_user.id)
    budgets = get_budget_usage(uid, current_month())

    if not budgets:
        await update.message.reply_text(
            "Belum ada budget. Buat dengan:\n/budget [kategori] [jumlah]\nContoh: /budget makan 1500000"
        )
        return

    text = "💰 *Status Budget Bulan Ini*\n\n"
    for b in budgets:
        pct = (b["spent"] / b["limit_amount"] * 100) if b["limit_amount"] else 0
        bar_len = min(int(pct / 10), 10)
        bar = "█" * bar_len + "░" * (10 - bar_len)
        status = "⚠️ MELEBIHI!" if pct > 100 else ("🔴 Hampir habis" if pct > 80 else "✅ Aman")
        text += (
            f"*{b['category'].upper()}*\n"
            f"`[{bar}]` {pct:.0f}%\n"
            f"{fmt_rp(b['spent'])} / {fmt_rp(b['limit_amount'])} — {status}\n\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")


async def tambah_tagihan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Usage: /tagihan PLN 500000 20"""
    if not allowed(update): return
    uid = str(update.effective_user.id)
    args = ctx.args

    if len(args) < 3:
        await update.message.reply_text(
            "Format: /tagihan [nama] [jumlah] [tanggal jatuh tempo]\n"
            "Contoh: /tagihan PLN 500000 20"
        )
        return

    name = args[0]
    try:
        amount = float(args[1].replace(".", "").replace(",", ""))
        due_day = int(args[2])
    except ValueError:
        await update.message.reply_text("Format jumlah atau tanggal tidak valid.")
        return

    add_bill(uid, name, amount, due_day)
    await update.message.reply_text(
        f"✅ Tagihan *{name}* sebesar *{fmt_rp(amount)}* (jatuh tempo tgl {due_day}) ditambahkan.",
        parse_mode="Markdown"
    )


async def list_tagihan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    uid = str(update.effective_user.id)
    bills = get_bills(uid)

    if not bills:
        await update.message.reply_text(
            "Belum ada tagihan. Tambah dengan:\n/tagihan [nama] [jumlah] [tgl]\nContoh: /tagihan Netflix 200000 5"
        )
        return

    text = "📋 *Tagihan Rutin*\n\n"
    total = 0
    for b in bills:
        text += f"• *{b['name']}*: {fmt_rp(b['amount'])} — setiap tgl {b['due_day']}\n"
        total += b["amount"]
    text += f"\n*Total per bulan: {fmt_rp(total)}*"

    await update.message.reply_text(text, parse_mode="Markdown")


# ── Main Message Handler ───────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return

    uid  = str(update.effective_user.id)
    text = update.message.text.strip()
    upsert_user(uid, update.effective_user.first_name)

    # Shortcut buttons
    shortcuts = {
        "📊 laporan bulan ini": laporan,
        "💰 sisa budget":       cek_budget,
        "📋 daftar tagihan":    list_tagihan,
        "❓ bantuan":           help_command,
    }
    for key, handler in shortcuts.items():
        if text.lower() == key:
            await handler(update, ctx)
            return

    # Show typing indicator
    await update.message.chat.send_action("typing")

    # Try to parse as transaction first
    parsed = parse_transaction(text)
    if parsed:
        add_transaction(
            uid,
            parsed["amount"],
            parsed["type"],
            parsed["category"],
            parsed["description"],
            parsed.get("date")
        )

        type_label = {"income": "Pemasukan", "expense": "Pengeluaran", "investment": "Investasi"}
        emoji      = {"income": "💚", "expense": "❤️", "investment": "💙"}
        e = emoji.get(parsed["type"], "✅")
        t = type_label.get(parsed["type"], parsed["type"])

        # Check budget warning
        warning = ""
        if parsed["type"] == "expense":
            budgets = get_budget_usage(uid, current_month())
            for b in budgets:
                if b["category"] == parsed["category"] and b["limit_amount"] > 0:
                    pct = b["spent"] / b["limit_amount"] * 100
                    if pct > 100:
                        warning = f"\n⚠️ Budget {parsed['category']} sudah melebihi limit! ({pct:.0f}%)"
                    elif pct > 80:
                        warning = f"\n🔴 Budget {parsed['category']} hampir habis ({pct:.0f}%)"

        # Tulis ke Google Sheet jika expense
        sheet_note = ""
        if parsed["type"] == "expense" and os.getenv("GOOGLE_SHEET_ID"):
            try:
                from app.sheets import write_transaction_to_sheet
                member = ctx.user_data.get("member", "al_riefqy")
                ok, pos = write_transaction_to_sheet(parsed, uid, member)
                if ok:
                    sheet_note = f"\n📊 Sheet: pos {pos}"
            except Exception as ex:
                sheet_note = f"\n⚠️ Sheet: {str(ex)[:40]}"

        await update.message.reply_text(
            f"{e} Tercatat!\n\n"
            f"{t}: {fmt_rp(parsed['amount'])}\n"
            f"Kategori: {parsed['category']}\n"
            f"Keterangan: {parsed['description']}"
            f"{sheet_note}{warning}",
        )
        return

    # Not a transaction — use smart process_message (auto-detect sheet/model)
    from app.advisor import process_message, needs_sheet_data
    summary = get_summary(uid, current_month())
    budgets = get_budget_usage(uid, current_month())
    bills   = get_bills(uid)
    monthly_ctx = {"summary": summary, "budgets": budgets, "bills": bills,
                   "month": datetime.now().strftime("%B %Y")}

    reply, model_used = process_message(text, monthly_context=monthly_ctx)

    # Tambah footer info model jika pakai Sonnet (biaya lebih tinggi)
    if "sonnet" in model_used:
        reply += "\n\n_🔍 Analisis mendalam (Sonnet)_"

    await update.message.reply_text(reply)


async def debug_sheet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Test koneksi Google Sheet — hanya untuk debugging."""
    if not allowed(update): return
    await update.message.chat.send_action("typing")

    lines = ["🔍 Debug Google Sheet:\n"]

    # Cek environment variables
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    creds    = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    lines.append(f"GOOGLE_SHEET_ID: {'✅ Ada' if sheet_id else '❌ KOSONG'}")
    lines.append(f"GOOGLE_CREDENTIALS_JSON: {'✅ Ada' if creds else '❌ KOSONG'}")

    if not sheet_id or not creds:
        await update.message.reply_text("\n".join(lines))
        return

    # Coba koneksi ke Sheet
    try:
        from app.sheets import get_all_sheet_data
        data = get_all_sheet_data()
        if data:
            lines.append(f"\n✅ Sheet terbaca: {len(data)} bulan data")
            lines.append(f"Bulan pertama: {data[0]['bulan']}")
            lines.append(f"Bulan terakhir: {data[-1]['bulan']}")
        else:
            lines.append("\n⚠️ Sheet terbuka tapi data kosong")
            lines.append("Cek apakah nama tab Sheet adalah '📥 Data'")
    except Exception as e:
        lines.append(f"\n❌ Error koneksi: {type(e).__name__}")
        lines.append(str(e)[:200])

    await update.message.reply_text("\n".join(lines))


async def cek_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cek email pending yang belum diproses."""
    if not allowed(update): return
    from app.webhook_server import get_pending_emails
    from app.database import add_transaction
    from app.sheets import write_transaction_to_sheet

    pending = get_pending_emails()
    if not pending:
        await update.message.reply_text("📭 Tidak ada email transaksi baru.")
        return

    results = []
    for email in pending:
        if email.get("type") == "info":
            results.append(f"ℹ️ {email['description']}")
            continue

        if email.get("amount", 0) > 0:
            # Simpan ke database
            add_transaction(
                str(update.effective_user.id),
                email["amount"],
                email["type"],
                email["category"],
                email["description"],
            )
            # Tulis ke Sheet
            sheet_note = ""
            if os.getenv("GOOGLE_SHEET_ID"):
                try:
                    member = "al_riefqy"
                    ok, pos = write_transaction_to_sheet(email, str(update.effective_user.id), member)
                    if ok:
                        sheet_note = f" → Sheet: {pos}"
                except:
                    pass

            emoji = "💚" if email["type"] == "income" else ("💙" if email["type"] == "investment" else "❤️")
            results.append(
                f"{emoji} {email['description']}\n"
                f"   Rp{email['amount']:,.0f} ({email['category']}){sheet_note}"
            )

    text = f"📧 {len(pending)} email diproses:\n\n" + "\n\n".join(results)
    await update.message.reply_text(text)


async def set_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Set anggota keluarga untuk transaksi berikutnya. /setmember tiwi"""
    if not allowed(update): return
    valid = ["tiwi", "al_riefqy", "mama", "shanaya", "tante", "rian"]
    if not ctx.args:
        current = ctx.user_data.get("member", "al_riefqy")
        await update.message.reply_text(
            f"Member aktif: {current}\n\n"
            f"Ganti dengan: /setmember [nama]\n"
            f"Pilihan: {', '.join(valid)}"
        )
        return
    member = ctx.args[0].lower().replace(" ", "_")
    if member not in valid:
        await update.message.reply_text(f"Member tidak valid. Pilihan: {', '.join(valid)}")
        return
    ctx.user_data["member"] = member
    await update.message.reply_text(
        f"✅ Member diset ke: {member}\n"
        f"Semua transaksi berikutnya akan dicatat ke pos {member} di Sheet."
    )


async def rekap_sheet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Rekap transaksi bulan ini ke tab Data. /rekap atau /rekap May 2026"""
    if not allowed(update): return
    bulan = " ".join(ctx.args) if ctx.args else datetime.now().strftime("%b %Y")
    await update.message.chat.send_action("typing")
    try:
        from app.sheets import rekap_bulan_ke_data
        ok, msg = rekap_bulan_ke_data(bulan)
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def tanya_sheet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Tanya apapun tentang data historis Google Sheet."""
    if not allowed(update): return

    pertanyaan = " ".join(ctx.args) if ctx.args else ""
    if not pertanyaan:
        await update.message.reply_text(
            "Contoh penggunaan:\n"
            "/tanya bulan mana pengeluaran paling boros?\n"
            "/tanya bandingkan nabung tahun 2024 vs 2025\n"
            "/tanya tren pengeluaran al riefqy 6 bulan terakhir\n"
            "/tanya total pengeluaran mama tahun 2025"
        )
        return

    await update.message.chat.send_action("typing")
    try:
        from app.sheets import get_all_sheet_data
        from app.advisor import ask_claude_with_sheet
        data = get_all_sheet_data()
        if not data:
            await update.message.reply_text("❌ Gagal membaca data dari Google Sheet.")
            return
        reply = ask_claude_with_sheet(pertanyaan, data)
        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


# ── Google Sheet Commands ──────────────────────────────
async def sheet_budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Baca budget bulan terakhir dari Google Sheet."""
    if not allowed(update): return
    await update.message.chat.send_action("typing")

    try:
        from app.sheets import get_budget_from_sheet
        data = get_budget_from_sheet()
        if not data:
            await update.message.reply_text("❌ Gagal membaca Google Sheet. Pastikan GOOGLE_CREDENTIALS_JSON dan GOOGLE_SHEET_ID sudah diset.")
            return

        # Gunakan plain text tanpa Markdown untuk hindari parse error
        lines = []
        lines.append(f"📊 Data Bulan: {data['bulan']}")
        lines.append("")
        lines.append(f"💰 Gaji         : {fmt_rp(data['gaji'])}")
        lines.append(f"🏦 Tabungan     : {fmt_rp(data['total_tabungan'])}")
        lines.append(f"🛒 Pengeluaran  : {fmt_rp(data['total_pengeluaran'])}")
        lines.append(f"📈 Nabung       : {data['pct_nabung']*100:.1f}%")
        lines.append("")
        lines.append("── Alokasi Tabungan ──")
        for k, v in data['tabungan'].items():
            if v > 0:
                lines.append(f"  {k:<12}: {fmt_rp(v)}")
        lines.append("")
        lines.append("── Pengeluaran per Pos ──")
        for k, v in data['pengeluaran'].items():
            if v > 0:
                lines.append(f"  {k:<12}: {fmt_rp(v)}")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def sheet_rekap(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Panduan rekap bulanan ke Google Sheet."""
    if not allowed(update): return

    bulan = datetime.now().strftime("%b %Y")
    text = (
        f"📝 *Rekap Bulanan ke Google Sheet*\n\n"
        f"Untuk input data {bulan} ke Sheet, kirim pesan dengan format:\n\n"
        f"`/input_bulan`\n\n"
        f"Bot akan tanya satu per satu:\n"
        f"1. Gaji bulan ini\n"
        f"2. Total tabungan & rinciannya\n"
        f"3. Total pengeluaran & rinciannya\n\n"
        f"Atau kamu bisa langsung input manual di Google Sheet seperti biasa."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── App Entry ──────────────────────────────────────────
def main():
    init_db()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN tidak ditemukan di .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start",          start))
    app.add_handler(CommandHandler("help",           help_command))
    app.add_handler(CommandHandler("laporan",        laporan))
    app.add_handler(CommandHandler("transaksi",      transaksi_list))
    app.add_handler(CommandHandler("budget",         set_budget_cmd))
    app.add_handler(CommandHandler("cekbudget",      cek_budget))
    app.add_handler(CommandHandler("tagihan",        tambah_tagihan))
    app.add_handler(CommandHandler("tagihan_list",   list_tagihan))
    app.add_handler(CommandHandler("sheet_budget",   sheet_budget))
    app.add_handler(CommandHandler("sheet_rekap",    sheet_rekap))
    app.add_handler(CommandHandler("tanya",          tanya_sheet))
    app.add_handler(CommandHandler("setmember",      set_member))
    app.add_handler(CommandHandler("rekap",          rekap_sheet))
    app.add_handler(CommandHandler("cek_email",      cek_email))
    app.add_handler(CommandHandler("debug_sheet",    debug_sheet))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Fin Finance Bot berjalan...")

    # Jalankan webhook server paralel di port 8080
    import asyncio
    from aiohttp import web as aiohttp_web
    from app.webhook_server import create_app as create_webhook_app

    async def run_both():
        webhook_app = create_webhook_app()
        runner = aiohttp_web.AppRunner(webhook_app)
        await runner.setup()
        site = aiohttp_web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8080)))
        await site.start()
        logger.info("🌐 Webhook server berjalan di port 8080")
        # Jalankan polling bot
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        # Tunggu selamanya
        await asyncio.Event().wait()

    asyncio.run(run_both())


if __name__ == "__main__":
    main()

