import os
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly"
]

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
BOT_SHEET_NAME = "📱 Transaksi Bot"

# ── Mapping kategori bot → kolom pengeluaran Sheet ─────
# Siapa yang input akan menentukan kolom mana yang di-update
MEMBER_COLS = {
    "tiwi":      "tiwi",
    "al_riefqy": "al_riefqy",
    "alriefqy":  "al_riefqy",
    "al riefqy": "al_riefqy",
    "riefqy":    "al_riefqy",
    "mama":      "mama",
    "shanaya":   "shanaya",
    "tante":     "tante",
    "rian":      "rian",
}

# Mapping kategori transaksi → pos pengeluaran Sheet
CATEGORY_TO_POS = {
    # Kebutuhan rumah
    "transport": "bus",
    "bus":       "bus",
    "listrik":   "listrik",
    "wifi":      "wifi",
    "internet":  "wifi",
    "hutang":    "hutang",
    "cicilan":   "hutang",
    # Pribadi default ke al_riefqy (bisa di-override oleh member)
    "makan":     "al_riefqy",
    "belanja":   "al_riefqy",
    "kesehatan": "al_riefqy",
    "hiburan":   "al_riefqy",
    "gadget":    "al_riefqy",
    "pendidikan":"ukt",
    "ukt":       "ukt",
    # Default
    "lainnya":   "others",
    "tagihan":   "others",
}

# Header tab Transaksi Bot
BOT_TAB_HEADERS = [
    "Tanggal", "Bulan", "Deskripsi", "Kategori", "Pos Sheet",
    "Anggota", "Jumlah (Rp)", "Tipe", "Dicatat oleh (TG ID)"
]


def get_client():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON tidak ditemukan")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

def get_spreadsheet():
    return get_client().open_by_key(SPREADSHEET_ID)

def get_sheet(sheet_name="📥 Data"):
    return get_spreadsheet().worksheet(sheet_name)


# ── Setup tab Transaksi Bot ────────────────────────────
def ensure_bot_tab():
    """Buat tab 📱 Transaksi Bot jika belum ada."""
    try:
        ss = get_spreadsheet()
        try:
            ws = ss.worksheet(BOT_SHEET_NAME)
            return ws  # sudah ada
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(title=BOT_SHEET_NAME, rows=1000, cols=10)
            # Tulis header
            ws.append_row(BOT_TAB_HEADERS)
            # Format header (bold)
            ws.format("A1:I1", {"textFormat": {"bold": True},
                                 "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.6}})
            return ws
    except Exception as e:
        print(f"ensure_bot_tab error: {e}")
        return None


# ── Tulis transaksi ke tab Bot ─────────────────────────
def write_transaction_to_sheet(transaction: dict, telegram_id: str, member: str = "al_riefqy") -> tuple[bool, str]:
    """
    Tulis satu transaksi ke tab 📱 Transaksi Bot.
    transaction = {amount, type, category, description, date}
    member = nama anggota keluarga (tiwi/al_riefqy/mama/dll)
    """
    try:
        ws = ensure_bot_tab()
        if not ws:
            return False, "Gagal akses tab Bot"

        # Tentukan pos Sheet berdasarkan member + kategori
        pos = resolve_pos(transaction.get("category", ""), member)

        date_str = transaction.get("date") or datetime.now().strftime("%Y-%m-%d")
        bulan = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %Y")

        row = [
            date_str,                           # Tanggal
            bulan,                              # Bulan
            transaction.get("description", ""), # Deskripsi
            transaction.get("category", ""),    # Kategori
            pos,                                # Pos Sheet
            member,                             # Anggota
            transaction.get("amount", 0),       # Jumlah
            transaction.get("type", "expense"), # Tipe
            telegram_id,                        # TG ID
        ]
        ws.append_row(row)
        return True, pos

    except Exception as e:
        return False, str(e)


def resolve_pos(category: str, member: str) -> str:
    """
    Tentukan kolom pos Sheet berdasarkan kategori + anggota.
    Prioritas: member khusus > kategori spesifik > others
    """
    cat = category.lower().strip()
    mem = member.lower().strip()

    # Pos khusus yang tidak bergantung member
    fixed_pos = ["bus", "listrik", "wifi", "hutang", "ukt"]
    if cat in fixed_pos:
        return cat
    if cat in CATEGORY_TO_POS and CATEGORY_TO_POS[cat] in fixed_pos:
        return CATEGORY_TO_POS[cat]

    # Pos berdasarkan member
    if mem in MEMBER_COLS:
        return MEMBER_COLS[mem]

    # Fallback ke kategori mapping
    return CATEGORY_TO_POS.get(cat, "others")


# ── Rekap bulanan ke tab Data ──────────────────────────
def rekap_bulan_ke_data(bulan_str: str) -> tuple[bool, str]:
    """
    Rekap semua transaksi dari tab Bot untuk bulan tertentu
    dan update/insert ke tab 📥 Data.
    bulan_str = "May 2026"
    """
    try:
        # Ambil semua transaksi bulan ini dari tab Bot
        ws_bot = get_sheet(BOT_SHEET_NAME)
        all_rows = ws_bot.get_all_values()

        if len(all_rows) <= 1:
            return False, "Belum ada transaksi di tab Bot"

        headers = all_rows[0]
        transaksi = []
        for row in all_rows[1:]:
            if len(row) < 7:
                continue
            if row[1] == bulan_str:  # kolom Bulan
                transaksi.append({
                    "tanggal":  row[0],
                    "bulan":    row[1],
                    "deskripsi":row[2],
                    "kategori": row[3],
                    "pos":      row[4],
                    "anggota":  row[5],
                    "jumlah":   float(str(row[6]).replace(",","") or 0),
                    "tipe":     row[7] if len(row) > 7 else "expense",
                })

        if not transaksi:
            return False, f"Tidak ada transaksi bulan {bulan_str} di tab Bot"

        # Hitung total per pos pengeluaran
        pos_totals = {
            "tiwi": 0, "al_riefqy": 0, "mama": 0, "shanaya": 0,
            "tante": 0, "ukt": 0, "rian": 0, "bus": 0,
            "listrik": 0, "wifi": 0, "hutang": 0, "others": 0
        }
        total_exp = 0
        for t in transaksi:
            if t["tipe"] == "expense":
                pos = t["pos"]
                if pos in pos_totals:
                    pos_totals[pos] += t["jumlah"]
                else:
                    pos_totals["others"] += t["jumlah"]
                total_exp += t["jumlah"]

        # Cari baris bulan ini di tab Data
        ws_data = get_sheet("📥 Data")
        all_data = ws_data.get_all_values()

        target_row = None
        for i, row in enumerate(all_data):
            if len(row) > 1 and row[1] == bulan_str:
                target_row = i + 1  # 1-indexed
                break

        if target_row:
            # Update kolom pengeluaran di baris yang sudah ada
            # Kolom V-AH = index 22-34 (1-indexed)
            updates = [
                (target_row, 22, pos_totals["tiwi"]),
                (target_row, 23, pos_totals["al_riefqy"]),
                (target_row, 24, pos_totals["mama"]),
                (target_row, 25, pos_totals["shanaya"]),
                (target_row, 26, pos_totals["tante"]),
                (target_row, 27, pos_totals["ukt"]),
                (target_row, 28, pos_totals["rian"]),
                (target_row, 29, pos_totals["bus"]),
                (target_row, 30, pos_totals["listrik"]),
                (target_row, 31, pos_totals["wifi"]),
                (target_row, 32, pos_totals["hutang"]),
                (target_row, 33, pos_totals["others"]),
                (target_row, 34, total_exp),
            ]
            for row_i, col_i, val in updates:
                ws_data.update_cell(row_i, col_i, val)

            return True, f"✅ Rekap {bulan_str} berhasil diupdate di tab Data!\nTotal pengeluaran: Rp{total_exp:,.0f}\n\nDetail:\n" + \
                "\n".join(f"  {k}: Rp{v:,.0f}" for k, v in pos_totals.items() if v > 0)
        else:
            return False, f"Baris {bulan_str} tidak ditemukan di tab Data. Silakan tambah dulu secara manual atau gunakan /input_bulan."

    except Exception as e:
        return False, f"Error rekap: {e}"


# ── Read functions ─────────────────────────────────────
def get_all_sheet_data() -> list:
    try:
        ws = get_sheet("📥 Data")
        all_values = ws.get_all_values()

        def safe_float(val):
            try:
                return float(str(val).replace(",", "").replace(" ", "") or 0)
            except:
                return 0.0

        months = []
        for row in all_values:
            if len(row) < 2: continue
            bulan = str(row[1]).strip()
            if not any(m in bulan for m in ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]):
                continue
            if "TOTAL" in bulan.upper(): continue

            months.append({
                "bulan": bulan,
                "gaji":              safe_float(row[3])  if len(row) > 3  else 0,
                "total_tabungan":    safe_float(row[4])  if len(row) > 4  else 0,
                "total_pengeluaran": safe_float(row[5])  if len(row) > 5  else 0,
                "pct_nabung":        safe_float(row[6])  if len(row) > 6  else 0,
                "sisa":              safe_float(row[7])  if len(row) > 7  else 0,
                "tabungan": {
                    "haji":    safe_float(row[10]) if len(row) > 10 else 0,
                    "cicilan": safe_float(row[11]) if len(row) > 11 else 0,
                    "darurat": safe_float(row[12]) if len(row) > 12 else 0,
                    "anak":    safe_float(row[13]) if len(row) > 13 else 0,
                    "liburan": safe_float(row[14]) if len(row) > 14 else 0,
                    "mobil":   safe_float(row[15]) if len(row) > 15 else 0,
                    "renovasi":safe_float(row[16]) if len(row) > 16 else 0,
                    "pensiun": safe_float(row[17]) if len(row) > 17 else 0,
                },
                "pengeluaran": {
                    "tiwi":      safe_float(row[21]) if len(row) > 21 else 0,
                    "al_riefqy": safe_float(row[22]) if len(row) > 22 else 0,
                    "mama":      safe_float(row[23]) if len(row) > 23 else 0,
                    "shanaya":   safe_float(row[24]) if len(row) > 24 else 0,
                    "tante":     safe_float(row[25]) if len(row) > 25 else 0,
                    "ukt":       safe_float(row[26]) if len(row) > 26 else 0,
                    "rian":      safe_float(row[27]) if len(row) > 27 else 0,
                    "bus":       safe_float(row[28]) if len(row) > 28 else 0,
                    "listrik":   safe_float(row[29]) if len(row) > 29 else 0,
                    "wifi":      safe_float(row[30]) if len(row) > 30 else 0,
                    "hutang":    safe_float(row[31]) if len(row) > 31 else 0,
                    "others":    safe_float(row[32]) if len(row) > 32 else 0,
                }
            })
        return months
    except Exception as e:
        print(f"Error get_all_sheet_data: {e}")
        return []


def get_budget_from_sheet():
    try:
        ws = get_sheet("📥 Data")
        all_values = ws.get_all_values()

        def safe_float(val):
            try:
                return float(str(val).replace(",","").replace(" ","") or 0)
            except:
                return 0.0

        data_rows = []
        for i, row in enumerate(all_values):
            if len(row) > 1 and any(m in str(row[1]) for m in ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]):
                if "TOTAL" not in str(row[1]).upper():
                    data_rows.append((i, row))

        if not data_rows:
            return None

        last_idx, last_row = data_rows[-1]

        return {
            "bulan": last_row[1],
            "gaji":               safe_float(last_row[3])  if len(last_row) > 3  else 0,
            "total_tabungan":     safe_float(last_row[4])  if len(last_row) > 4  else 0,
            "total_pengeluaran":  safe_float(last_row[5])  if len(last_row) > 5  else 0,
            "pct_nabung":         safe_float(last_row[6])  if len(last_row) > 6  else 0,
            "tabungan": {
                "haji":    safe_float(last_row[10]) if len(last_row) > 10 else 0,
                "cicilan": safe_float(last_row[11]) if len(last_row) > 11 else 0,
                "darurat": safe_float(last_row[12]) if len(last_row) > 12 else 0,
                "anak":    safe_float(last_row[13]) if len(last_row) > 13 else 0,
                "liburan": safe_float(last_row[14]) if len(last_row) > 14 else 0,
                "mobil":   safe_float(last_row[15]) if len(last_row) > 15 else 0,
                "renovasi":safe_float(last_row[16]) if len(last_row) > 16 else 0,
                "pensiun": safe_float(last_row[17]) if len(last_row) > 17 else 0,
            },
            "pengeluaran": {
                "tiwi":      safe_float(last_row[21]) if len(last_row) > 21 else 0,
                "al_riefqy": safe_float(last_row[22]) if len(last_row) > 22 else 0,
                "mama":      safe_float(last_row[23]) if len(last_row) > 23 else 0,
                "shanaya":   safe_float(last_row[24]) if len(last_row) > 24 else 0,
                "tante":     safe_float(last_row[25]) if len(last_row) > 25 else 0,
                "ukt":       safe_float(last_row[26]) if len(last_row) > 26 else 0,
                "rian":      safe_float(last_row[27]) if len(last_row) > 27 else 0,
                "bus":       safe_float(last_row[28]) if len(last_row) > 28 else 0,
                "listrik":   safe_float(last_row[29]) if len(last_row) > 29 else 0,
                "wifi":      safe_float(last_row[30]) if len(last_row) > 30 else 0,
                "hutang":    safe_float(last_row[31]) if len(last_row) > 31 else 0,
                "others":    safe_float(last_row[32]) if len(last_row) > 32 else 0,
            }
        }
    except Exception as e:
        print(f"Error reading sheet: {e}")
        return None


def write_monthly_data(data: dict):
    try:
        ws = get_sheet("📥 Data")
        all_values = ws.get_all_values()
        total_row_idx = None
        for i, row in enumerate(all_values):
            if len(row) > 1 and "TOTAL" in str(row[1]).upper():
                total_row_idx = i + 1
                break
        if total_row_idx is None:
            return False, "Baris TOTAL tidak ditemukan"
        new_row = [""] * 35
        new_row[1]  = data.get("bulan", "")
        new_row[2]  = data.get("tahun", datetime.now().year)
        new_row[3]  = data.get("gaji", 0)
        new_row[4]  = data.get("tabungan", 0)
        new_row[5]  = data.get("pengeluaran", 0)
        new_row[6]  = data.get("pct_nabung", 0)
        new_row[7]  = data.get("sisa", 0)
        new_row[10] = data.get("tab_haji", 0)
        new_row[11] = data.get("tab_cicilan", 0)
        new_row[12] = data.get("tab_darurat", 0)
        new_row[13] = data.get("tab_anak", 0)
        new_row[14] = data.get("tab_liburan", 0)
        new_row[15] = data.get("tab_mobil", 0)
        new_row[16] = data.get("tab_renovasi", 0)
        new_row[17] = data.get("tab_pensiun", 0)
        new_row[18] = data.get("total_sav", 0)
        new_row[21] = data.get("exp_tiwi", 0)
        new_row[22] = data.get("exp_al_riefqy", 0)
        new_row[23] = data.get("exp_mama", 0)
        new_row[24] = data.get("exp_shanaya", 0)
        new_row[25] = data.get("exp_tante", 0)
        new_row[26] = data.get("exp_ukt", 0)
        new_row[27] = data.get("exp_rian", 0)
        new_row[28] = data.get("exp_bus", 0)
        new_row[29] = data.get("exp_listrik", 0)
        new_row[30] = data.get("exp_wifi", 0)
        new_row[31] = data.get("exp_hutang", 0)
        new_row[32] = data.get("exp_others", 0)
        new_row[33] = data.get("total_exp", 0)
        ws.insert_row(new_row, total_row_idx)
        return True, f"Data {data.get('bulan')} berhasil ditulis ke Google Sheet!"
    except Exception as e:
        return False, f"Error: {e}"
