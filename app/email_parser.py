import re
import anthropic
import os

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Regex parser (tanpa token) untuk email umum ────────
def parse_mandiri_email(subject: str, body: str) -> dict | None:
    """
    Parse email notifikasi Mandiri tanpa Claude (hemat token).
    Return dict transaksi atau None jika tidak relevan.
    """
    text = f"{subject}\n{body}".lower()

    # Cek apakah ini notifikasi transaksi
    keywords = ["debet", "kredit", "transfer", "pembayaran", "pembelian",
                 "penarikan", "transaksi", "tagihan", "belanja"]
    if not any(k in text for k in keywords):
        return None

    # Extract nominal
    amount = None
    patterns = [
        r"rp\.?\s*([\d,\.]+)",
        r"idr\s*([\d,\.]+)",
        r"sebesar\s*rp\.?\s*([\d,\.]+)",
        r"nominal\s*rp\.?\s*([\d,\.]+)",
        r"([\d,\.]+)\s*(?:idr|rupiah)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            raw = m.group(1).replace(".", "").replace(",", "")
            try:
                amount = float(raw)
                if amount > 100:  # filter noise
                    break
            except:
                continue

    if not amount:
        return None

    # Tentukan tipe
    tipe = "expense"
    if any(k in text for k in ["kredit", "masuk", "terima", "incoming"]):
        tipe = "income"

    # Extract merchant/deskripsi
    desc = extract_merchant(subject, body)

    # Mapping kategori otomatis dari merchant
    category = guess_category(desc, text)

    return {
        "source": "mandiri",
        "amount": amount,
        "type": tipe,
        "category": category,
        "description": desc,
        "raw_subject": subject,
    }


def parse_bibit_email(subject: str, body: str) -> dict | None:
    """
    Parse email notifikasi Bibit (pembelian reksa dana, update portfolio).
    """
    text = f"{subject}\n{body}".lower()

    bibit_keywords = ["bibit", "reksa dana", "reksadana", "pembelian unit",
                       "penjualan unit", "portfolio", "nav", "unit penyertaan"]
    if not any(k in text for k in bibit_keywords):
        return None

    amount = None
    patterns = [r"rp\.?\s*([\d,\.]+)", r"idr\s*([\d,\.]+)"]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            raw = m.group(1).replace(".", "").replace(",", "")
            try:
                val = float(raw)
                if val > 100:
                    amount = val
                    break
            except:
                continue

    if not amount:
        # Tidak ada nominal tapi mungkin update portofolio
        if "portfolio" in text or "nilai" in text:
            return {
                "source": "bibit",
                "amount": 0,
                "type": "info",
                "category": "investasi",
                "description": f"Update Bibit: {subject[:80]}",
                "raw_subject": subject,
            }
        return None

    tipe = "investment"
    if any(k in text for k in ["penjualan", "pencairan", "redeem"]):
        tipe = "income"

    # Extract nama reksa dana
    desc = extract_bibit_product(subject, body)

    return {
        "source": "bibit",
        "amount": amount,
        "type": tipe,
        "category": "reksa-dana",
        "description": desc,
        "raw_subject": subject,
    }


def parse_email_with_claude(subject: str, body: str, source: str) -> dict | None:
    """
    Fallback: gunakan Claude Haiku jika regex gagal.
    Hanya dipanggil jika parse biasa tidak berhasil.
    """
    prompt = f"""Parse email notifikasi keuangan berikut dan ekstrak informasi transaksi.
Balas HANYA dengan JSON, tidak ada teks lain:
{{
  "amount": <angka atau 0>,
  "type": "expense|income|investment|info",
  "category": "makan|transport|belanja|tagihan|kesehatan|hiburan|pendidikan|gadget|reksa-dana|lainnya",
  "description": "<deskripsi singkat max 50 karakter>",
  "is_transaction": true|false
}}

Subject: {subject[:200]}
Body: {body[:500]}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        import json
        data = json.loads(response.content[0].text.strip())
        if not data.get("is_transaction"):
            return None
        data["source"] = source
        data["raw_subject"] = subject
        return data
    except Exception as e:
        print(f"Claude email parse error: {e}")
        return None


# ── Helpers ────────────────────────────────────────────
def extract_merchant(subject: str, body: str) -> str:
    """Extract nama merchant dari email."""
    # Coba dari subject dulu
    patterns = [
        r"(?:di|at|ke|to|merchant|toko)\s*[:\-]?\s*([A-Za-z0-9\s]{3,30})",
        r"(?:pembayaran|payment|belanja)\s+(?:di\s+)?([A-Za-z0-9\s]{3,30})",
    ]
    for pat in patterns:
        m = re.search(pat, subject, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:50]

    # Fallback: ambil kata-kata penting dari subject
    words = subject.split()
    skip = {"re:", "fw:", "fwd:", "notifikasi", "transaksi", "mandiri",
            "bank", "anda", "dengan", "untuk", "dari", "kartu"}
    meaningful = [w for w in words if w.lower() not in skip and len(w) > 2]
    return " ".join(meaningful[:5]) if meaningful else subject[:50]


def extract_bibit_product(subject: str, body: str) -> str:
    """Extract nama produk reksa dana dari email Bibit."""
    patterns = [
        r"(?:pembelian|penjualan|subscription)\s+([A-Za-z\s]+(?:saham|pendapatan|pasar uang|campuran)[A-Za-z\s]*)",
        r"produk[:\s]+([A-Za-z\s]+)",
    ]
    text = f"{subject} {body}"
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:50]
    return f"Bibit: {subject[:50]}"


def guess_category(desc: str, text: str) -> str:
    """Tebak kategori dari deskripsi dan isi email."""
    text_lower = (desc + " " + text).lower()
    mapping = {
        "makan": ["indomaret", "alfamart", "resto", "restaurant", "cafe",
                   "kafe", "mcd", "kfc", "grab food", "gofood", "shopeefood",
                   "warung", "makan", "food", "bakery"],
        "transport": ["grab", "gojek", "gocar", "grabcar", "taxi", "ojek",
                       "pertamina", "bensin", "bbm", "shell", "spbu", "tol",
                       "parkir", "busway", "commuter", "kereta"],
        "belanja": ["shopee", "tokopedia", "lazada", "blibli", "zalora",
                     "uniqlo", "h&m", "supermarket", "hypermart", "carrefour"],
        "tagihan": ["pln", "listrik", "pdam", "air", "telkom", "indihome",
                     "wifi", "internet", "bpjs", "asuransi"],
        "kesehatan": ["apotek", "kimia farma", "klinik", "rumah sakit",
                       "dokter", "guardian", "century"],
        "pendidikan": ["sekolah", "kampus", "ukt", "spp", "kursus", "udemy"],
        "gadget": ["iphone", "samsung", "apple", "oppo", "xiaomi",
                    "erafone", "ibox", "istana gadget"],
    }
    for cat, keywords in mapping.items():
        if any(kw in text_lower for kw in keywords):
            return cat
    return "lainnya"


def process_incoming_email(subject: str, body: str, sender: str) -> dict | None:
    """
    Main entry point — deteksi sumber email dan parse.
    Returns parsed transaction dict atau None.
    """
    sender_lower = sender.lower()
    subject_lower = subject.lower()

    # Deteksi sumber
    is_mandiri = any(k in sender_lower or k in subject_lower
                     for k in ["mandiri", "bankmandiri", "livin"])
    is_bibit   = any(k in sender_lower or k in subject_lower
                     for k in ["bibit", "noreply@bibit"])

    result = None
    if is_mandiri:
        result = parse_mandiri_email(subject, body)
        if not result:
            result = parse_email_with_claude(subject, body, "mandiri")
    elif is_bibit:
        result = parse_bibit_email(subject, body)
        if not result:
            result = parse_email_with_claude(subject, body, "bibit")
    else:
        # Email keuangan lain — coba dengan Claude
        result = parse_email_with_claude(subject, body, "other")

    return result
