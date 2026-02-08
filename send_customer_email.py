#!/usr/bin/env python3
"""
Mikroilmastoanalyysi - Customer Email

Lähettää emailin loppuasiakkaalle kun QA on hyväksynyt analyysin.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict

# Gmail API
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import base64

# Konfiguraatio
EMAIL_CREDENTIALS = Path("/home/eetu/apps/email_manager/config/email_credentials.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_customer_email(task: Dict, dry_run: bool = False) -> bool:
    """
    Lähettää tuloslinkki loppuasiakkaalle.

    Args:
        task: Task dictionary
        dry_run: Jos True, ei lähetä oikeasti

    Returns:
        True jos onnistui
    """
    customer_email = task.get("email")
    customer_name = task.get("nimi")
    address = task.get("osoite")
    results_url = task.get("results_url")

    # Vanhentuminen
    expires_at = task.get("customer_link_expires_at", "")
    if expires_at:
        try:
            expires_dt = datetime.fromisoformat(expires_at)
            expires_str = expires_dt.strftime("%d.%m.%Y")
        except:
            expires_str = "30 päivän kuluttua"
    else:
        expires_str = "30 päivän kuluttua"

    # Aihe
    subject = f"📊 Mikroilmastoanalyysisi on valmis - {address[:50]}"

    # HTML body
    body_html = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 700px; margin: 0 auto;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 32px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: white; margin: 0; font-size: 32px;">Analyysisi on valmis!</h1>
    </div>

    <div style="background: white; padding: 32px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px;">
        <p style="font-size: 18px; margin-top: 0;">Hei {customer_name},</p>

        <p>Tilauksenne <strong>mikroilmastoanalyysi</strong> on nyt valmis!</p>

        <div style="background: #f7fafc; padding: 24px; border-radius: 8px; margin: 24px 0; border-left: 4px solid #667eea;">
            <h3 style="margin-top: 0; color: #2c5aa0;">📍 Kohde</h3>
            <p style="font-size: 16px; margin-bottom: 0;"><strong>{address}</strong></p>
        </div>

        <div style="text-align: center; margin: 32px 0;">
            <a href="{results_url}" style="display: inline-block; background: #667eea; color: white; padding: 16px 48px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 18px; box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);">
                📊 Avaa tulokset
            </a>
        </div>

        <div style="background: #ecfdf5; padding: 20px; border-radius: 8px; border-left: 4px solid #10b981; margin: 24px 0;">
            <h3 style="margin-top: 0; color: #047857;">📦 Analyysi sisältää:</h3>
            <ul style="margin: 0; padding-left: 20px;">
                <li><strong>PDF-raportit</strong> tuulianalyysistä eri tuulensuunnista</li>
                <li><strong>Visualisoinnit</strong> (PNG-kuvat)</li>
                <li><strong>WDR-analyysi</strong> (kosteusrasitus julkisivuilla)</li>
                <li><strong>QA-dashboardit</strong> (HTML)</li>
            </ul>
        </div>

        <div style="background: #fef3c7; padding: 16px; border-radius: 8px; margin: 24px 0; border-left: 4px solid #f59e0b;">
            <p style="margin: 0; font-size: 14px;">
                <strong>⏳ Linkki voimassa:</strong> {expires_str}<br>
                Suosittelemme lataamaan tiedostot omalle koneellesi.
            </p>
        </div>

        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 32px 0;">

        <p style="margin-bottom: 8px;">Ystävällisin terveisin,</p>
        <p style="font-weight: bold; margin: 0;">Loopshore</p>
        <p style="font-size: 14px; color: #666; margin-top: 4px;">
            <a href="https://www.loopshore.fi" style="color: #667eea;">www.loopshore.fi</a>
        </p>

        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 32px 0;">

        <p style="font-size: 12px; color: #888; text-align: center;">
            Tämä on automaattinen ilmoitus Loopshore mikroilmastoanalyysi-palvelusta.<br>
            Jos sinulla on kysyttävää, vastaa tähän emailiin.
        </p>
    </div>
</body>
</html>
"""

    # Plain text fallback
    body_text = f"""
MIKROILMASTOANALYYSISI ON VALMIS!

Hei {customer_name},

Tilauksenne mikroilmastoanalyysi on nyt valmis!

KOHDE:
{address}

TULOKSET:
{results_url}

ANALYYSI SISÄLTÄÄ:
• PDF-raportit tuulianalyysistä eri tuulensuunnista
• Visualisoinnit (PNG-kuvat)
• WDR-analyysi (kosteusrasitus julkisivuilla)
• QA-dashboardit (HTML)

LINKKI VOIMASSA:
{expires_str}

Suosittelemme lataamaan tiedostot omalle koneellesi.

Ystävällisin terveisin,
Loopshore
www.loopshore.fi

---
Tämä on automaattinen ilmoitus Loopshore mikroilmastoanalyysi-palvelusta.
Jos sinulla on kysyttävää, vastaa tähän emailiin.
"""

    if dry_run:
        logger.info("[DRY-RUN] Would send customer email:")
        logger.info(f"  To: {customer_email}")
        logger.info(f"  Subject: {subject}")
        return True

    # Lähetä email
    try:
        # Autentikoi
        creds = Credentials.from_authorized_user_file(str(EMAIL_CREDENTIALS), SCOPES)
        service = build("gmail", "v1", credentials=creds)

        # Luo viesti
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["To"] = customer_email

        part1 = MIMEText(body_text, "plain", "utf-8")
        part2 = MIMEText(body_html, "html", "utf-8")
        message.attach(part1)
        message.attach(part2)

        # Lähetä
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        service.users().messages().send(
            userId="me",
            body={"raw": raw_message}
        ).execute()

        logger.info(f"Customer email sent to: {customer_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send customer email: {e}")
        return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-uuid", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Load task
    import json
    tasks_file = Path("/home/eetu/apps/email_manager/data/mikroilmasto_tasks.json")
    with open(tasks_file) as f:
        data = json.load(f)

    task = None
    for t in data["tasks"]:
        if t.get("simulation_uuid") == args.task_uuid:
            task = t
            break

    if not task:
        print(f"Task not found: {args.task_uuid}")
        sys.exit(1)

    success = send_customer_email(task, dry_run=args.dry_run)
    sys.exit(0 if success else 1)
