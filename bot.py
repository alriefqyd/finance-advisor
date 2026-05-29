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

    # Try to parse as transaction
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
                        warning = f"\n\n⚠️ *Budget {parsed['category']} sudah melebihi limit!* ({pct:.0f}%)"
                    elif pct > 80:
                        warning = f"\n\n🔴 Budget *{parsed['category']}* hampir habis ({pct:.0f}%)"

        await update.message.reply_text(
            f"{e} Tercatat!\n\n"
            f"*{t}*: {fmt_rp(parsed['amount'])}\n"
            f"Kategori: {parsed['category']}\n"
            f"Keterangan: {parsed['description']}{warning}",
            parse_mode="Markdown"
        )
        return

    # Otherwise, treat as advice/question
    summary = get_summary(uid, current_month())
    budgets = get_budget_usage(uid, current_month())
    bills   = get_bills(uid)

    reply = get_advice(text, summary, budgets, bills)
    await update.message.reply_text(reply, parse_mode="Markdown")


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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Fin Finance Bot berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
