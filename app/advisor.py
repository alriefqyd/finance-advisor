import anthropic
import json
import os
from datetime import datetime

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """Kamu adalah Fin, asisten keuangan pribadi keluarga Indonesia yang cerdas, ramah, dan jujur.

TUGASMU:
1. Membantu mencatat transaksi keuangan dari percakapan natural
2. Menganalisis kondisi keuangan dan memberi laporan ringkas
3. Memberikan rekomendasi bijak soal pengeluaran (termasuk gadget, elektronik, dll)
4. Mengingatkan anggaran dan tagihan

ATURAN PENTING:
- Gunakan bahasa Indonesia yang santai tapi profesional
- Selalu gunakan format Rupiah (Rp) dengan titik sebagai pemisah ribuan
- Jujur dan tidak melebih-lebihkan; kalau kondisi keuangan kurang baik, katakan dengan sopan
- Untuk rekomendasi pembelian barang, pertimbangkan: sisa budget, tabungan, dan kebutuhan nyata
- Hindari saran investasi spesifik (saham tertentu, kripto) — arahkan ke konsultasi profesional

CARA PARSE TRANSAKSI:
Ketika user menyebut transaksi, ekstrak dan balas HANYA dengan JSON ini (tidak ada teks lain):
{
  "action": "add_transaction",
  "amount": <angka>,
  "type": "expense|income|investment",
  "category": "<kategori>",
  "description": "<deskripsi singkat>",
  "date": "<YYYY-MM-DD atau null untuk hari ini>"
}

Kategori expense: makan, transport, belanja, tagihan, kesehatan, hiburan, pendidikan, gadget, lainnya
Kategori income: gaji, bonus, freelance, bisnis, lainnya
Kategori investment: tabungan, deposito, reksa-dana, properti, lainnya

Jika pesan BUKAN transaksi, balas dengan teks biasa (bukan JSON).
Jika tidak yakin apakah itu transaksi, tanya balik dengan ramah."""


def ask_claude(user_message: str, context: dict = None) -> str:
    """
    Send a message to Claude with optional financial context.
    Uses prompt caching on the system prompt to save costs.
    """
    messages = []

    # Inject financial context if provided
    if context:
        context_text = _build_context(context)
        messages.append({
            "role": "user",
            "content": f"[DATA KEUANGAN SAYA BULAN INI]\n{context_text}\n\n[PESAN SAYA]\n{user_message}"
        })
    else:
        messages.append({"role": "user", "content": user_message})

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}  # 90% cheaper on repeat calls
            }
        ],
        messages=messages
    )

    return response.content[0].text


def parse_transaction(text: str) -> dict | None:
    """
    Ask Claude to parse a potential transaction from natural text.
    Returns dict if transaction found, None otherwise.
    """
    result = ask_claude(text)

    # Try to parse as JSON
    try:
        stripped = result.strip()
        if stripped.startswith("{"):
            data = json.loads(stripped)
            if data.get("action") == "add_transaction":
                return data
    except (json.JSONDecodeError, KeyError):
        pass

    return None


def get_advice(user_message: str, summary: list, budgets: list, bills: list) -> str:
    """Get financial advice with full context."""
    context = {
        "summary": summary,
        "budgets": budgets,
        "bills": bills,
        "month": datetime.now().strftime("%B %Y")
    }
    return ask_claude(user_message, context)


def _build_context(context: dict) -> str:
    lines = [f"Bulan: {context.get('month', '-')}"]

    # Summary
    if context.get("summary"):
        lines.append("\nRingkasan Transaksi:")
        income = sum(r["total"] for r in context["summary"] if r["type"] == "income")
        expense = sum(r["total"] for r in context["summary"] if r["type"] == "expense")
        invest = sum(r["total"] for r in context["summary"] if r["type"] == "investment")
        lines.append(f"  Pemasukan  : Rp{income:,.0f}")
        lines.append(f"  Pengeluaran: Rp{expense:,.0f}")
        lines.append(f"  Investasi  : Rp{invest:,.0f}")
        lines.append(f"  Sisa       : Rp{income - expense - invest:,.0f}")

        lines.append("\nPer Kategori (Pengeluaran):")
        for r in context["summary"]:
            if r["type"] == "expense":
                lines.append(f"  {r['category']}: Rp{r['total']:,.0f}")

    # Budgets
    if context.get("budgets"):
        lines.append("\nStatus Budget:")
        for b in context["budgets"]:
            pct = (b["spent"] / b["limit_amount"] * 100) if b["limit_amount"] else 0
            status = "⚠️ MELEBIHI" if pct > 100 else ("🔴 HAMPIR HABIS" if pct > 80 else "✅ AMAN")
            lines.append(
                f"  {b['category']}: Rp{b['spent']:,.0f} / Rp{b['limit_amount']:,.0f} ({pct:.0f}%) {status}"
            )

    # Bills
    if context.get("bills"):
        lines.append("\nTagihan Aktif:")
        for bill in context["bills"]:
            lines.append(f"  {bill['name']}: Rp{bill['amount']:,.0f} (tgl {bill['due_day']})")

    return "\n".join(lines)
