# 🤖 Fin — Personal Finance Advisor Bot

Bot Telegram asisten keuangan keluarga berbasis Claude AI (Haiku 4.5).

## Fitur
- ✅ Catat transaksi via chat natural (tanpa form)
- ✅ Laporan pemasukan, pengeluaran, investasi per bulan
- ✅ Manajemen budget per kategori + alert otomatis
- ✅ Pencatatan tagihan rutin
- ✅ Saran keuangan & rekomendasi pembelian dari AI
- ✅ Multi-user (whitelist anggota keluarga)

---

## Setup Lokal (Development)

### 1. Clone & Install
```bash
git clone <repo-kamu>
cd finance-advisor
pip install -r requirements.txt
```

### 2. Buat Bot Telegram
1. Chat ke **@BotFather** di Telegram
2. Ketik `/newbot` → ikuti instruksi
3. Salin **token** yang diberikan

### 3. Dapatkan API Key Anthropic
1. Buka **console.anthropic.com**
2. Daftar / login
3. Buat API Key baru di menu "API Keys"
4. Top up minimal $5 (cukup untuk beberapa bulan)

### 4. Cari Telegram User ID
1. Chat ke **@userinfobot** di Telegram
2. Salin angka ID yang muncul
3. Lakukan untuk semua anggota keluarga

### 5. Konfigurasi .env
```bash
cp .env.example .env
# Edit .env dengan token dan API key kamu
```

### 6. Jalankan
```bash
python bot.py
```

---

## Deploy ke Railway (Gratis)

### 1. Push ke GitHub
```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/username/fin-bot.git
git push -u origin main
```

### 2. Deploy di Railway
1. Buka **railway.app** → Login dengan GitHub
2. Klik **New Project** → **Deploy from GitHub repo**
3. Pilih repo `fin-bot`
4. Klik **Variables** → tambahkan semua isi dari `.env`:
   - `TELEGRAM_BOT_TOKEN`
   - `ANTHROPIC_API_KEY`
   - `ALLOWED_USER_IDS`
   - `DB_PATH` = `data/finance.db`
5. Railway otomatis deploy menggunakan Dockerfile

> ⚠️ **Penting:** Railway free tier di-sleep setelah idle.
> Untuk bot Telegram yang selalu aktif, upgrade ke Hobby ($5/bulan)
> atau gunakan VPS murah seperti Hetzner (€4/bulan).

---

## Cara Pakai

### Catat Transaksi (chat natural)
```
"beli makan siang 35rb"
"bayar bensin 150 ribu"
"terima gaji 8 juta"
"transfer ke tabungan 500rb"
"beli pulsa 50000"
```

### Perintah
| Perintah | Fungsi |
|---|---|
| /laporan | Ringkasan keuangan bulan ini |
| /transaksi | 10 transaksi terakhir |
| /budget makan 1500000 | Set budget makan Rp1.500.000/bulan |
| /cekbudget | Status semua budget |
| /tagihan PLN 500000 20 | Tambah tagihan PLN Rp500.000 jatuh tempo tgl 20 |
| /tagihan_list | Daftar semua tagihan |

### Tanya Saran AI
```
"boleh beli iPhone 16 bulan ini?"
"kondisi keuangan aku bulan ini gimana?"
"rekomendasi laptop buat kerja budget 10 juta"
"aku harus nabung berapa biar bisa beli motor?"
```

---

## Estimasi Biaya Bulanan

| Komponen | Biaya |
|---|---|
| Railway Hobby | $5/bulan |
| Claude Haiku 4.5 (~75 pesan/hari, 4 user) | ~$4-6/bulan |
| **Total** | **~$9-11/bulan (~Rp160.000-200.000)** |

*Dengan Prompt Caching aktif, biaya API bisa lebih hemat hingga 50%.*

---

## Struktur Proyek
```
finance-advisor/
├── bot.py              # Main bot & handlers
├── app/
│   ├── database.py     # SQLite operations
│   └── advisor.py      # Claude AI integration
├── data/
│   └── finance.db      # Database (auto-created)
├── requirements.txt
├── Dockerfile
└── .env.example
```
