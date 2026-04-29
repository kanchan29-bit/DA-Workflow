
import imaplib
import email
import os
import zipfile
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================
EMAIL_USER = "kanchan.bishnoi@inditronics.com"
EMAIL_PASS = "hnqj quqc lqmz pgmj" # App Password (NO spaces)

IMAP_SERVER = "imap.gmail.com"

DOWNLOAD_DIR = r"C:\Users\kanch\Desktop\statement\Sessions\fp\downloads"
EXTRACT_DIR = r"C:\Users\kanch\Desktop\statement\Sessions\fp\New folder"

SUBJECT_FILTER = "Fingerprint Data"

# ============================================================
# SETUP
# ============================================================
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(EXTRACT_DIR, exist_ok=True)

# ============================================================
# CONNECT TO EMAIL
# ============================================================
mail = imaplib.IMAP4_SSL(IMAP_SERVER)
mail.login(EMAIL_USER, EMAIL_PASS)
mail.select("inbox")

# ============================================================
# FETCH ONLY TODAY'S EMAILS WITH SUBJECT
# ============================================================
today_imap = datetime.now().strftime("%d-%b-%Y")  # e.g. "17-Apr-2026"
today_date = datetime.now().date()

status, messages = mail.search(None, f'(SINCE "{today_imap}" SUBJECT "{SUBJECT_FILTER}")')
email_ids = messages[0].split()

print(f"Total matching emails today: {len(email_ids)}")

# ============================================================
# FIND LATEST EMAIL FROM TODAY
# ============================================================
latest_email = None
latest_datetime = None

for e_id in email_ids:
    status, msg_data = mail.fetch(e_id, "(RFC822)")

    for response_part in msg_data:
        if isinstance(response_part, tuple):
            msg = email.message_from_bytes(response_part[1])

            # Parse email date
            email_datetime = email.utils.parsedate_to_datetime(msg["Date"])
            email_date = email_datetime.date()

            # Safety check: ensure it's truly today (SINCE can include yesterday near midnight)
            if email_date != today_date:
                continue

            # Keep latest
            if (latest_datetime is None) or (email_datetime > latest_datetime):
                latest_datetime = email_datetime
                latest_email = msg

# ============================================================
# PROCESS LATEST EMAIL
# ============================================================
if latest_email is None:
    print("❌ No email found for today with given subject.")
else:
    print(f"✅ Processing latest email from: {latest_datetime}")

    for part in latest_email.walk():
        if part.get_content_maintype() == "multipart":
            continue
        
        if part.get("Content-Disposition") is None:
            continue

        filename = part.get_filename()

        if filename and filename.endswith(".zip"):
            filepath = os.path.join(DOWNLOAD_DIR, filename)

            # Save ZIP
            with open(filepath, "wb") as f:
                f.write(part.get_payload(decode=True))

            print(f"📥 Downloaded: {filename}")

            # Extract ZIP
            with zipfile.ZipFile(filepath, 'r') as zip_ref:
                zip_ref.extractall(EXTRACT_DIR)

            print(f"📂 Extracted: {filename}")

# ============================================================
# CLEANUP
# ============================================================
mail.logout()

print("🎯 Done.")