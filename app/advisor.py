import anthropic
import json
import os
import time
from datetime import datetime

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Sheet data cache (10 menit) ────────────────────────
_sheet_cache = {"data": None, "ts": 0}
CACHE_TTL = 600  # 10 menit

SYSTEM_PROMPT = """Kamu adalah Fin, asisten keuangan pribadi keluarga Al Riefqy yang cerdas, ramah, dan jujur.

STRUKTUR KELUARGA & ANGGARAN:
Pengeluaran rutin per bulan dibagi ke:
- Tiwi (istri): kebutuhan pribadi istri
- Al Riefqy: kebutuhan pribadi suami
- Mama: support orang tua
- Shanaya: kebutuhan anak
- Tante: support keluarga
- UKT Rina: biaya kuliah
- Rian: support keluarga
- Bus: transportasi
- Listrik: tagihan listrik
- Wifi: tagihan internet
- Hutang: cicilan/hutang
- Others: pengeluaran tidak terduga

Tabungan rutin per bulan:
- Haji: dana ibadah haji
- Cicilan Rumah: KPR/cicilan
- Darurat: dana darurat
- Anak: tabungan pendidikan anak
- Liburan: dana liburan keluarga
- Mobil: pajak & perawatan kendaraan
- Renovasi Rumah: perbaikan rumah
- Pensiun: dana pensiun

Portofolio investasi via Bibit (reksa dana).
Data historis tersimpan di Google Sheet "Laporan Keuangan Keluarga".

TUGASMU:
1. Bantu catat transaksi harian dari chat natural
2. Analisis dan jawab pertanyaan keuangan dari data historis Sheet
3. Beri rekomendasi pembelian / pengeluaran berdasarkan kondisi nyata
4. Beri saran keuangan yang jujur dan kontekstual

ATURAN PENTING:
- Bahasa Indonesia santai tapi profesional
- Format Rupiah: Rp1.500.000 (titik sebagai pemisah ribuan)
- Jujur meski kondisi keuangan kurang baik
- Hindari saran investasi spesifik (saham/kripto tertentu)

DETEKSI INTENT — tentukan salah satu:
1. TRANSAKSI → user menyebut nominal + aktivitas beli/bayar/terima
   Balas HANYA JSON:
   {"action":"add_transaction","amount":<angka>,"type":"expense|income|investment","category":"<kat>","description":"<desk>","date":"<YYYY-MM-DD|null>"}
   Kategori expense: makan,transport,belanja,tagihan,kesehatan,hiburan,pendidikan,gadget,lainnya
   Kategori income: gaji,bonus,freelance,bisnis,lainnya
   Kategori investment: tabungan,deposito,reksa-dana,properti,lainnya

2. ANALISIS SHEET → pertanyaan tentang data historis, tren, perbandingan
   Jawab dengan analisis dari data Sheet yang diberikan

3. SARAN/LAINNYA → pertanyaan umum keuangan, rekomendasi beli, dll
   Jawab berdasarkan konteks yang tersedia

Jika tidak yakin antara 1 dan 3, tanya balik dengan ramah."""


# ── Keyword detector — apakah perlu data Sheet? ────────
SHEET_KEYWORDS = [
    # Waktu
    "bulan lalu", "tahun lalu", "tahun ini", "bulan terakhir", "bulan ini",
    "2 bulan", "3 bulan", "6 bulan", "12 bulan", "sejak", "selama", "sepanjang",
    "2023", "2024", "2025", "2026",
    "januari", "februari", "maret", "april", "mei", "juni",
    "juli", "agustus", "september", "oktober", "november", "desember",
    # Analisis
    "historis", "tren", "trend", "bandingkan", "perbandingan", "rata-rata",
    "total", "paling", "tertinggi", "terendah", "boros", "hemat",
    "meningkat", "menurun", "naik", "turun", "progress", "perkembangan",
    "berapa bulan", "kapan", "summary", "rekap", "evaluasi",
    # Pertanyaan keuangan umum yang butuh data
    "kondisi keuangan", "gimana kondisi", "gimana keuangan",
    "alokasi", "budget", "pengeluaran", "pemasukan", "tabungan",
    "nabung", "saving", "gaji", "sisa", "cashflow",
    # Anggota keluarga
    "tiwi", "al riefqy", "mama", "shanaya", "tante", "rian",
    # Pos keuangan
    "haji", "pensiun", "darurat", "renovasi", "liburan", "bibit",
    "cicilan", "listrik", "wifi", "transport",
    # Pertanyaan rekomendasi yang butuh konteks
    "boleh beli", "bisa beli", "mampu beli", "sanggup",
    "berapa lagi", "target", "kapan bisa",
]

def needs_sheet_data(text: str) -> bool:
    """
    Selalu tarik Sheet kecuali pesan sangat pendek (salam/transaksi singkat).
    Lebih baik punya konteks historis daripada tidak.
    """
    text_lower = text.lower().strip()
    words = text_lower.split()

    # Pesan 1-2 kata → tidak perlu Sheet (salam, command pendek)
    if len(words) <= 2:
        return False

    # Pesan yang jelas transaksi (ada angka + kata beli/bayar)
    has_number = any(c.isdigit() for c in text)
    transaction_words = ["beli", "bayar", "beli", "terima", "gaji masuk",
                          "transfer", "tarik", "setor", "rb", "ribu", "juta"]
    if has_number and any(w in text_lower for w in transaction_words):
        return False

    # Semua pertanyaan lain → tarik Sheet
    return True


# ── Cache helper ───────────────────────────────────────
def get_cached_sheet_data():
    global _sheet_cache
    now = time.time()
    if _sheet_cache["data"] and (now - _sheet_cache["ts"]) < CACHE_TTL:
        return _sheet_cache["data"], True  # (data, from_cache)
    try:
        from app.sheets import get_all_sheet_data
        data = get_all_sheet_data()
        if data:
            _sheet_cache = {"data": data, "ts": now}
            print(f"✅ Sheet loaded: {len(data)} bulan")
        else:
            print("⚠️ Sheet returned empty data")
        return data, False
    except Exception as e:
        print(f"❌ Sheet cache error: {type(e).__name__}: {e}")
        return [], False


# ── Model selector ─────────────────────────────────────
def pick_model(text: str) -> str:
    """
    Haiku untuk query sederhana/transaksi.
    Sonnet untuk analisis kompleks (panjang pertanyaan atau kata kunci analitis).
    """
    complex_keywords = [
        "bandingkan", "analisis", "evaluasi", "proyeksi", "rekomendasi lengkap",
        "strategi", "rencana", "optimasi", "breakdown", "detail semua"
    ]
    is_complex = len(text) > 120 or any(kw in text.lower() for kw in complex_keywords)
    return "claude-sonnet-4-5" if is_complex else "claude-haiku-4-5"


# ── Build sheet context string ─────────────────────────
def _build_sheet_context(sheet_data: list) -> str:
    lines = [f"DATA KEUANGAN KELUARGA AL RIEFQY — {len(sheet_data)} bulan (Google Sheet)\n"]
    lines.append(f"{'Bulan':<12} {'Gaji':>8} {'Tabung':>8} {'Keluar':>8} {'%Nabung':>8}")
    lines.append("-" * 50)
    for row in sheet_data:
        pct = f"{row.get('pct_nabung',0)*100:.0f}%"
        lines.append(
            f"{str(row.get('bulan','')):<12}"
            f"{_short(row.get('gaji',0)):>8}"
            f"{_short(row.get('total_tabungan',0)):>8}"
            f"{_short(row.get('total_pengeluaran',0)):>8}"
            f"{pct:>8}"
        )
    # Detail 3 bulan terakhir
    lines.append("\nDETAIL 3 BULAN TERAKHIR:")
    for row in sheet_data[-3:]:
        lines.append(f"\n{row.get('bulan','')} — Pengeluaran:")
        for k, v in row.get('pengeluaran', {}).items():
            if v > 0: lines.append(f"  {k}: {_short(v)}")
        lines.append(f"{row.get('bulan','')} — Tabungan:")
        for k, v in row.get('tabungan', {}).items():
            if v > 0: lines.append(f"  {k}: {_short(v)}")
    return "\n".join(lines)


def _short(amount: float) -> str:
    if amount >= 1_000_000: return f"{amount/1_000_000:.1f}jt"
    if amount >= 1_000: return f"{amount/1_000:.0f}rb"
    return str(int(amount))

# Keep old name as alias
fmt_rp_short = _short


# ── Main entry point ───────────────────────────────────
def process_message(text: str, monthly_context: dict = None) -> tuple[str, str]:
    """
    Proses pesan user secara otomatis:
    - Deteksi intent (transaksi / analisis sheet / saran)
    - Pilih model yang tepat
    - Ambil data Sheet dari cache jika perlu
    Returns: (response_text, model_used)
    """
    model = pick_model(text)
    use_sheet = needs_sheet_data(text)
    messages = []

    if use_sheet:
        sheet_data, from_cache = get_cached_sheet_data()
        sheet_ctx = _build_sheet_context(sheet_data) if sheet_data else ""
        content = f"[DATA GOOGLE SHEET]\n{sheet_ctx}\n\n[PESAN]\n{text}"
        if monthly_context:
            monthly_txt = _build_monthly_context(monthly_context)
            content = f"[DATA GOOGLE SHEET]\n{sheet_ctx}\n\n[DATA BULAN INI]\n{monthly_txt}\n\n[PESAN]\n{text}"
    elif monthly_context:
        monthly_txt = _build_monthly_context(monthly_context)
        content = f"[DATA BULAN INI]\n{monthly_txt}\n\n[PESAN]\n{text}"
    else:
        content = text

    messages.append({"role": "user", "content": content})

    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=messages
    )
    return response.content[0].text, model


# ── Helpers ────────────────────────────────────────────
def parse_transaction(text: str) -> dict | None:
    result, _ = process_message(text)
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
    context = {"summary": summary, "budgets": budgets, "bills": bills,
                "month": datetime.now().strftime("%B %Y")}
    result, _ = process_message(user_message, monthly_context=context)
    return result


def ask_claude_with_sheet(user_message: str, sheet_data: list) -> str:
    """Legacy — tetap tersedia untuk /tanya command."""
    ctx = _build_sheet_context(sheet_data)
    response = client.messages.create(
        model=pick_model(user_message),
        max_tokens=1500,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"[DATA GOOGLE SHEET]\n{ctx}\n\n[PERTANYAAN]\n{user_message}"}]
    )
    return response.content[0].text


def _build_monthly_context(context: dict) -> str:
    lines = [f"Bulan: {context.get('month', '-')}"]
    if context.get("summary"):
        income  = sum(r["total"] for r in context["summary"] if r["type"] == "income")
        expense = sum(r["total"] for r in context["summary"] if r["type"] == "expense")
        invest  = sum(r["total"] for r in context["summary"] if r["type"] == "investment")
        lines.append(f"Pemasukan: {_short(income)} | Pengeluaran: {_short(expense)} | Investasi: {_short(invest)} | Sisa: {_short(income-expense-invest)}")
        for r in context["summary"]:
            if r["type"] == "expense":
                lines.append(f"  {r['category']}: {_short(r['total'])}")
    if context.get("budgets"):
        lines.append("Budget:")
        for b in context["budgets"]:
            pct = (b["spent"]/b["limit_amount"]*100) if b["limit_amount"] else 0
            status = "MELEBIHI" if pct > 100 else ("HAMPIR HABIS" if pct > 80 else "AMAN")
            lines.append(f"  {b['category']}: {_short(b['spent'])}/{_short(b['limit_amount'])} ({pct:.0f}%) {status}")
    if context.get("bills"):
        lines.append("Tagihan:")
        for bill in context["bills"]:
            lines.append(f"  {bill['name']}: {_short(bill['amount'])} tgl {bill['due_day']}")
    return "\n".join(lines)


# Legacy aliases
def ask_claude(user_message: str, context: dict = None) -> str:
    result, _ = process_message(user_message, monthly_context=context)
    return result