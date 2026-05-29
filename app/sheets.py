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

# Mapping kolom sheet ke index (sesuai struktur Data kamu)
# Bagian A: B=Bulan, C=Tahun, D=Gaji, E=Tabungan, F=Pengeluaran, G=%Nabung, H=Sisa
# Bagian C (Pengeluaran): V=Tiwi, W=AlRiefqy, X=Mama, Y=Shanaya, Z=Tante, AA=UKT, AB=Rian, AC=Bus, AD=Listrik, AE=Wifi, AF=Hutang, AG=Others, AH=Total Exp
# Bagian B (Tabungan): K=Haji, L=Cicilan, M=Darurat, N=Anak, O=Liburan, P=Mobil, Q=Perbaikan Rumah, R=Pensiun, S=Total Sav

COL_MAP = {
    "bulan": 2,       # B
    "tahun": 3,       # C
    "gaji": 4,        # D
    "tabungan": 5,    # E
    "pengeluaran": 6, # F
    "pct_nabung": 7,  # G
    "sisa": 8,        # H
    # Tabungan
    "haji": 11,       # K
    "cicilan": 12,    # L
    "darurat": 13,    # M
    "anak": 14,       # N
    "liburan": 15,    # O
    "mobil": 16,      # P
    "renovasi": 17,   # Q
    "pensiun": 18,    # R
    "total_sav": 19,  # S
    # Pengeluaran
    "tiwi": 22,       # V
    "al_riefqy": 23,  # W
    "mama": 24,       # X
    "shanaya": 25,    # Y
    "tante": 26,      # Z
    "ukt": 27,        # AA
    "rian": 28,       # AB
    "bus": 29,        # AC
    "listrik": 30,    # AD
    "wifi": 31,       # AE
    "hutang": 32,     # AF
    "others": 33,     # AG
    "total_exp": 34,  # AH
}

def get_client():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON tidak ditemukan di environment")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

def get_sheet(sheet_name="📥 Data"):
    client = get_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet(sheet_name)

def get_budget_from_sheet():
    """
    Baca data bulan terakhir dari Google Sheet sebagai referensi budget.
    Returns dict berisi alokasi tabungan dan pengeluaran bulan terakhir.
    """
    try:
        ws = get_sheet("📥 Data")
        all_values = ws.get_all_values()
        
        # Cari baris TOTAL (row terakhir sebelum total)
        data_rows = []
        for i, row in enumerate(all_values):
            if len(row) > 1 and row[1] and row[1] != "BULAN" and "TOTAL" not in str(row[1]).upper() and "Edit" not in str(row[1]):
                try:
                    # Cek apakah kolom bulan ada format bulan
                    if any(m in str(row[1]) for m in ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]):
                        data_rows.append((i, row))
                except:
                    pass
        
        if not data_rows:
            return None
        
        # Ambil baris terakhir (bulan terbaru)
        last_idx, last_row = data_rows[-1]
        
        def safe_float(val):
            try:
                return float(str(val).replace(",", "").replace(".", "").replace(" ", "") or 0)
            except:
                return 0.0

        return {
            "bulan": last_row[1] if len(last_row) > 1 else "-",
            "gaji": safe_float(last_row[3]) if len(last_row) > 3 else 0,
            "total_tabungan": safe_float(last_row[4]) if len(last_row) > 4 else 0,
            "total_pengeluaran": safe_float(last_row[5]) if len(last_row) > 5 else 0,
            "pct_nabung": safe_float(last_row[6]) if len(last_row) > 6 else 0,
            # Tabungan per kategori
            "tabungan": {
                "haji": safe_float(last_row[10]) if len(last_row) > 10 else 0,
                "cicilan": safe_float(last_row[11]) if len(last_row) > 11 else 0,
                "darurat": safe_float(last_row[12]) if len(last_row) > 12 else 0,
                "anak": safe_float(last_row[13]) if len(last_row) > 13 else 0,
                "liburan": safe_float(last_row[14]) if len(last_row) > 14 else 0,
                "mobil": safe_float(last_row[15]) if len(last_row) > 15 else 0,
                "renovasi": safe_float(last_row[16]) if len(last_row) > 16 else 0,
                "pensiun": safe_float(last_row[17]) if len(last_row) > 17 else 0,
            },
            # Pengeluaran per kategori
            "pengeluaran": {
                "tiwi": safe_float(last_row[21]) if len(last_row) > 21 else 0,
                "al_riefqy": safe_float(last_row[22]) if len(last_row) > 22 else 0,
                "mama": safe_float(last_row[23]) if len(last_row) > 23 else 0,
                "shanaya": safe_float(last_row[24]) if len(last_row) > 24 else 0,
                "tante": safe_float(last_row[25]) if len(last_row) > 25 else 0,
                "ukt": safe_float(last_row[26]) if len(last_row) > 26 else 0,
                "rian": safe_float(last_row[27]) if len(last_row) > 27 else 0,
                "bus": safe_float(last_row[28]) if len(last_row) > 28 else 0,
                "listrik": safe_float(last_row[29]) if len(last_row) > 29 else 0,
                "wifi": safe_float(last_row[30]) if len(last_row) > 30 else 0,
                "hutang": safe_float(last_row[31]) if len(last_row) > 31 else 0,
                "others": safe_float(last_row[32]) if len(last_row) > 32 else 0,
            }
        }
    except Exception as e:
        print(f"Error reading sheet: {e}")
        return None

def write_monthly_data(data: dict):
    """
    Tulis data bulan baru ke Google Sheet (insert row sebelum baris TOTAL).
    data = {
        bulan, tahun, gaji, tabungan, pengeluaran, pct_nabung, sisa,
        tab_haji, tab_cicilan, tab_darurat, tab_anak, tab_liburan,
        tab_mobil, tab_renovasi, tab_pensiun, total_sav,
        exp_tiwi, exp_al_riefqy, exp_mama, exp_shanaya, exp_tante,
        exp_ukt, exp_rian, exp_bus, exp_listrik, exp_wifi,
        exp_hutang, exp_others, total_exp
    }
    """
    try:
        ws = get_sheet("📥 Data")
        all_values = ws.get_all_values()
        
        # Cari index baris TOTAL
        total_row_idx = None
        for i, row in enumerate(all_values):
            if len(row) > 1 and "TOTAL" in str(row[1]).upper():
                total_row_idx = i + 1  # 1-indexed untuk gspread
                break
        
        if total_row_idx is None:
            return False, "Baris TOTAL tidak ditemukan di sheet"
        
        # Build row kosong 34 kolom (A-AH)
        new_row = [""] * 35
        new_row[1]  = data.get("bulan", "")
        new_row[2]  = data.get("tahun", datetime.now().year)
        new_row[3]  = data.get("gaji", 0)
        new_row[4]  = data.get("tabungan", 0)
        new_row[5]  = data.get("pengeluaran", 0)
        new_row[6]  = data.get("pct_nabung", 0)
        new_row[7]  = data.get("sisa", 0)
        # Tabungan
        new_row[10] = data.get("tab_haji", 0)
        new_row[11] = data.get("tab_cicilan", 0)
        new_row[12] = data.get("tab_darurat", 0)
        new_row[13] = data.get("tab_anak", 0)
        new_row[14] = data.get("tab_liburan", 0)
        new_row[15] = data.get("tab_mobil", 0)
        new_row[16] = data.get("tab_renovasi", 0)
        new_row[17] = data.get("tab_pensiun", 0)
        new_row[18] = data.get("total_sav", 0)
        # Pengeluaran
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
        
        # Insert row sebelum TOTAL
        ws.insert_row(new_row, total_row_idx)
        return True, f"✅ Data {data.get('bulan')} berhasil ditulis ke Google Sheet!"
    
    except Exception as e:
        return False, f"Error menulis ke sheet: {e}"

def get_ringkasan_sheet():
    """Ambil data ringkasan dari sheet Ringkasan."""
    try:
        ws = get_sheet("🏠 Ringkasan")
        values = ws.get_all_values()
        # Ambil baris ke-8 (Total Pemasukan, Tabungan, Pengeluaran, % Nabung, Bulan)
        for row in values:
            for cell in row:
                if str(cell).replace(",","").replace(".","").isdigit() and int(str(cell).replace(",","").replace(".","")) > 100000000:
                    pass
        return values
    except Exception as e:
        return None
