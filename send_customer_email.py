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
    subject = f"Mikroilmastoanalyysi valmis – {address[:50]}"

    # HTML body
    body_html = f"""
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #F1F1F2; font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #071922; line-height: 1.6;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #F1F1F2;">
        <tr>
            <td align="center" style="padding: 24px 16px;">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%;">

                    <!-- Header -->
                    <tr>
                        <td style="background-color: #F1F1F2; padding: 32px 40px 24px 40px;">
                            <img src="https://microclimateanalysis.com/assets/loopshore-logo-dark.png" alt="Loopshore" width="180" style="display: block; width: 180px; height: auto; border: 0;">
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="background-color: #FFFFFF; padding: 40px;">
                            <p style="font-size: 16px; margin: 0 0 20px 0;">Hei {customer_name},</p>

                            <p style="margin: 0 0 32px 0;">Tilauksenne mikroilmastoanalyysi on valmis.</p>

                            <!-- Kohde -->
                            <p style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #6B7280; margin: 0 0 6px 0;">Kohde</p>
                            <p style="font-size: 16px; font-weight: 600; margin: 0 0 32px 0;">{address}</p>

                            <!-- CTA Button -->
                            <table role="presentation" cellpadding="0" cellspacing="0" style="margin: 0 0 32px 0;">
                                <tr>
                                    <td style="background-color: #44E3A7; border-radius: 6px;">
                                        <a href="{results_url}" style="display: inline-block; padding: 14px 40px; color: #071922; text-decoration: none; font-weight: 600; font-size: 15px;">Avaa tulokset</a>
                                    </td>
                                </tr>
                            </table>

                            <!-- Sisältölista -->
                            <p style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #6B7280; margin: 0 0 10px 0;">Analyysi sisältää</p>
                            <table role="presentation" cellpadding="0" cellspacing="0" style="margin: 0 0 32px 0;">
                                <tr><td style="padding: 3px 0; color: #374151; font-size: 14px;">&#8226;&ensp;PDF-raportit tuulianalyysistä eri tuulensuunnista</td></tr>
                                <tr><td style="padding: 3px 0; color: #374151; font-size: 14px;">&#8226;&ensp;Visualisoinnit (PNG-kuvat)</td></tr>
                                <tr><td style="padding: 3px 0; color: #374151; font-size: 14px;">&#8226;&ensp;WDR-analyysi (kosteusrasitus julkisivuilla)</td></tr>
                                <tr><td style="padding: 3px 0; color: #374151; font-size: 14px;">&#8226;&ensp;QA-dashboardit (HTML)</td></tr>
                            </table>

                            <!-- Voimassaolo -->
                            <p style="font-size: 13px; color: #6B7280; margin: 0 0 32px 0;">
                                Linkki voimassa {expires_str}. Suosittelemme lataamaan tiedostot omalle koneellesi.
                            </p>

                            <!-- Allekirjoitus -->
                            <div style="border-top: 1px solid #E8E8E8; padding-top: 24px; margin-top: 8px;">
                                <p style="margin: 0 0 4px 0; font-size: 14px;">Ystävällisin terveisin,</p>
                                <p style="margin: 0; font-size: 14px; font-weight: 600;">Loopshore</p>
                            </div>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #F1F1F2; padding: 24px 40px; text-align: center;">
                            <p style="margin: 0 0 4px 0; font-size: 12px; color: #6B7280;">Loopshore Oy</p>
                            <p style="margin: 0 0 12px 0; font-size: 12px; color: #9CA3AF;">Tämä on automaattinen ilmoitus. Jos sinulla on kysyttävää, vastaa tähän emailiin.</p>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""

    # Plain text fallback
    body_text = f"""Hei {customer_name},

Tilauksenne mikroilmastoanalyysi on valmis.

KOHDE
{address}

TULOKSET
{results_url}

ANALYYSI SISÄLTÄÄ
- PDF-raportit tuulianalyysistä eri tuulensuunnista
- Visualisoinnit (PNG-kuvat)
- WDR-analyysi (kosteusrasitus julkisivuilla)
- QA-dashboardit (HTML)

Linkki voimassa {expires_str}. Suosittelemme lataamaan tiedostot omalle koneellesi.

Ystävällisin terveisin,
Loopshore

--
Loopshore Oy
Tämä on automaattinen ilmoitus. Jos sinulla on kysyttävää, vastaa tähän emailiin.
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
