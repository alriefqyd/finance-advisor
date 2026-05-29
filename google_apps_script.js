/**
 * Google Apps Script — Fin Finance Bot Email Watcher
 * 
 * CARA SETUP:
 * 1. Buka script.google.com → New Project
 * 2. Paste seluruh kode ini
 * 3. Ganti BOT_WEBHOOK_URL dan WEBHOOK_SECRET
 * 4. Klik Run → setupTrigger() sekali untuk aktifkan
 * 5. Beri izin akses Gmail saat diminta
 */

// ── CONFIG — GANTI INI ─────────────────────────────────
const BOT_WEBHOOK_URL = "https://your-railway-app.railway.app/webhook/email";
const WEBHOOK_SECRET  = "ganti_dengan_secret_kamu"; // sama dengan WEBHOOK_SECRET di Railway
const GMAIL_LABEL     = "bank-notif";   // label Gmail yang akan dipantau
const CHECK_LAST_MINS = 6;              // cek email N menit terakhir (trigger tiap 5 menit)
// ──────────────────────────────────────────────────────


/**
 * Fungsi utama — dipanggil otomatis tiap 5 menit oleh trigger.
 * Cek email baru berlabel "bank-notif" dan kirim ke bot.
 */
function checkNewEmails() {
  const now = new Date();
  const cutoff = new Date(now.getTime() - CHECK_LAST_MINS * 60 * 1000);

  // Cari email berlabel bank-notif yang belum diproses
  const query = `label:${GMAIL_LABEL} after:${formatGmailDate(cutoff)} -label:fin-processed`;
  const threads = GmailApp.search(query, 0, 20);

  if (threads.length === 0) return;

  // Label untuk tandai sudah diproses
  let processedLabel = GmailApp.getUserLabelByName("fin-processed");
  if (!processedLabel) {
    processedLabel = GmailApp.createLabel("fin-processed");
  }

  let sent = 0;
  threads.forEach(thread => {
    const messages = thread.getMessages();
    messages.forEach(msg => {
      if (msg.getDate() < cutoff) return;

      const payload = {
        subject: msg.getSubject(),
        body:    cleanBody(msg.getPlainBody()),
        sender:  msg.getFrom(),
        date:    msg.getDate().toISOString(),
        gmail_id: msg.getId(),
      };

      const success = sendToBot(payload);
      if (success) sent++;
    });

    // Tandai thread sudah diproses
    thread.addLabel(processedLabel);
  });

  if (sent > 0) {
    Logger.log(`Sent ${sent} emails to Fin Bot`);
  }
}


/**
 * Kirim data email ke webhook bot.
 */
function sendToBot(payload) {
  try {
    const options = {
      method: "post",
      contentType: "application/json",
      headers: { "X-Webhook-Secret": WEBHOOK_SECRET },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    };
    const response = UrlFetchApp.fetch(BOT_WEBHOOK_URL, options);
    const code = response.getResponseCode();
    Logger.log(`Bot response ${code}: ${response.getContentText().substring(0, 100)}`);
    return code === 200;
  } catch (e) {
    Logger.log(`Error sending to bot: ${e}`);
    return false;
  }
}


/**
 * Setup trigger — jalankan SEKALI untuk aktifkan pengecekan otomatis.
 */
function setupTrigger() {
  // Hapus trigger lama jika ada
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === "checkNewEmails") {
      ScriptApp.deleteTrigger(t);
    }
  });

  // Buat trigger baru setiap 5 menit
  ScriptApp.newTrigger("checkNewEmails")
    .timeBased()
    .everyMinutes(5)
    .create();

  Logger.log("✅ Trigger aktif — cek email setiap 5 menit");
}


/**
 * Test manual — jalankan ini untuk test tanpa menunggu trigger.
 */
function testManual() {
  Logger.log("Testing email check...");
  checkNewEmails();
  Logger.log("Done.");
}


// ── Helpers ────────────────────────────────────────────
function formatGmailDate(date) {
  // Format: YYYY/MM/DD untuk Gmail search query
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}/${m}/${d}`;
}

function cleanBody(body) {
  if (!body) return "";
  // Bersihkan whitespace berlebih, ambil max 1000 karakter
  return body.replace(/\s+/g, " ").trim().substring(0, 1000);
}


/**
 * Setup Gmail Filter — jalankan sekali untuk buat filter otomatis.
 * Filter: email dari Mandiri/Bibit → label "bank-notif"
 * 
 * Note: Gmail API tidak support buat filter via Apps Script.
 * Ikuti panduan manual di README.
 */
function showFilterInstructions() {
  const msg = `
SETUP GMAIL FILTER (manual):

1. Buka Gmail → Settings (⚙️) → See all settings
2. Klik tab "Filters and Blocked Addresses"
3. Klik "Create a new filter"
4. Di kolom "From", isi:
   notifikasi@bankmandiri.co.id OR noreply@bibit.id
5. Klik "Create filter"
6. Centang "Apply the label" → pilih "bank-notif" (buat baru jika belum ada)
7. Centang "Also apply filter to matching conversations"
8. Klik "Create filter"

Setelah ini, semua email Mandiri & Bibit otomatis berlabel "bank-notif".
  `;
  Logger.log(msg);
  Browser.msgBox(msg);
}
