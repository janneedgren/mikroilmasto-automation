#!/usr/bin/env python3
"""
Mikroilmastoanalyysi - QA Notification

Lähettää emailin QA-tiimille (Janne + Tuomas) analyysin valmistuttua.
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
QA_RECIPIENTS = [
    "janne.edgren@loopshore.com",
    "tuomas.alinikula@loopshore.com",
]

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_qa_notification(task: Dict, dry_run: bool = False) -> bool:
    """
    Lähettää QA-notifikaation Jannelle ja Tuomakselle.

    Args:
        task: Task dictionary
        dry_run: Jos True, ei lähetä oikeasti

    Returns:
        True jos onnistui
    """
    # Rakenna email
    success = task.get("status") not in ["failed"]

    if success:
        subject = f"QA-tarkistus: {task['osoite'][:50]}"
    else:
        subject = f"Simulaatio epäonnistui: {task['osoite'][:50]}"

    # Parametrit
    params = task.get("simulation_parameters", {})
    resolution = params.get("resolution", "1.0")
    wdr = "Kyllä" if params.get("wdr_enabled", True) else "Ei"

    # Kesto
    duration_s = task.get("simulation_duration_seconds", 0)
    duration_min = round(duration_s / 60, 1) if duration_s else "N/A"

    # Linkit
    results_url = task.get("results_url", "N/A")
    approval_token = task.get("qa_approval_token", "MISSING")
    uuid = task.get("simulation_uuid", "MISSING")

    approve_url = f"https://microclimateanalysis.com/approve/{uuid}/{approval_token}"
    reject_url = f"https://microclimateanalysis.com/reject/{uuid}/{approval_token}"

    # Vanhentuminen
    expires_at = task.get("qa_approval_expires_at", "")
    if expires_at:
        try:
            expires_dt = datetime.fromisoformat(expires_at)
            expires_str = expires_dt.strftime("%d.%m.%Y klo %H:%M")
        except:
            expires_str = expires_at
    else:
        expires_str = "N/A"

    # Virheviesti
    error_msg = task.get("error_message", "")

    # HTML body
    if success:
        status_row = f"""
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280; width: 140px;">Status</td>
                                    <td style="padding: 8px 0; font-size: 14px; font-weight: 600; color: #071922;">Onnistui</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">Kesto</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">{duration_min} min</td>
                                </tr>"""

        action_section = f"""
                            <!-- Viiva -->
                            <tr><td colspan="2" style="padding: 24px 0 0 0;"><div style="border-top: 1px solid #E8E8E8;"></div></td></tr>

                            <!-- Painikkeet -->
                            <tr>
                                <td colspan="2" style="padding: 24px 0;">
                                    <table role="presentation" cellpadding="0" cellspacing="0">
                                        <tr>
                                            <td style="background-color: #44E3A7; border-radius: 6px; padding: 0; margin: 0;">
                                                <a href="{approve_url}" style="display: inline-block; padding: 12px 32px; color: #071922; text-decoration: none; font-weight: 600; font-size: 14px;">HYVÄKSY</a>
                                            </td>
                                            <td style="width: 12px;"></td>
                                            <td style="border: 1px solid #D1D5DB; border-radius: 6px; padding: 0; margin: 0;">
                                                <a href="{reject_url}" style="display: inline-block; padding: 12px 32px; color: #6B7280; text-decoration: none; font-weight: 600; font-size: 14px;">HYLKÄÄ</a>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>

                            <!-- Huomautus -->
                            <tr>
                                <td colspan="2" style="padding: 0 0 8px 0;">
                                    <p style="font-size: 12px; color: #9CA3AF; margin: 0;">Hyväksyntä lähettää asiakkaalle automaattisesti linkin tuloksiin. Linkit voimassa {expires_str}.</p>
                                </td>
                            </tr>"""
    else:
        status_row = f"""
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280; width: 140px;">Status</td>
                                    <td style="padding: 8px 0; font-size: 14px; font-weight: 600; color: #071922;">Epäonnistui</td>
                                </tr>"""

        error_section = f"""
                            <!-- Virheviesti -->
                            <tr>
                                <td colspan="2" style="padding: 16px 0 0 0;">
                                    <p style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #6B7280; margin: 0 0 8px 0;">Virhe</p>
                                    <div style="background-color: #F1F1F2; padding: 12px 16px; border-radius: 4px;">
                                        <pre style="margin: 0; font-size: 12px; font-family: 'SF Mono', Monaco, Consolas, monospace; color: #374151; white-space: pre-wrap; word-break: break-word;">{error_msg}</pre>
                                    </div>
                                </td>
                            </tr>"""

        action_section = f"""
                            {error_section}

                            <!-- Viiva -->
                            <tr><td colspan="2" style="padding: 24px 0 0 0;"><div style="border-top: 1px solid #E8E8E8;"></div></td></tr>

                            <!-- Painike -->
                            <tr>
                                <td colspan="2" style="padding: 24px 0;">
                                    <table role="presentation" cellpadding="0" cellspacing="0">
                                        <tr>
                                            <td style="border: 1px solid #D1D5DB; border-radius: 6px; padding: 0; margin: 0;">
                                                <a href="{reject_url}" style="display: inline-block; padding: 12px 32px; color: #6B7280; text-decoration: none; font-weight: 600; font-size: 14px;">HYLKÄÄ</a>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>"""

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
                        <td style="background-color: #F1F1F2; padding: 32px 40px 8px 40px;">
                            <img src="https://microclimateanalysis.com/assets/loopshore-logo-dark.png" alt="Loopshore" width="180" style="display: block; width: 180px; height: auto; border: 0;">
                        </td>
                    </tr>
                    <tr>
                        <td style="background-color: #F1F1F2; padding: 4px 40px 24px 40px;">
                            <span style="font-size: 13px; color: #6B7280; letter-spacing: 0.5px;">QA-tarkistus</span>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="background-color: #FFFFFF; padding: 40px;">
                            <!-- Status -->
                            <p style="font-size: 18px; font-weight: 600; margin: 0 0 32px 0;">Simulaatio valmis</p>

                            <!-- Asiakas -->
                            <p style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #6B7280; margin: 0 0 8px 0;">Asiakas</p>
                            <table role="presentation" cellpadding="0" cellspacing="0" style="width: 100%; margin: 0 0 24px 0;">
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280; width: 140px;">Nimi</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">{task.get('nimi', 'N/A')}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">Email</td>
                                    <td style="padding: 8px 0; font-size: 14px;"><a href="mailto:{task.get('email', '')}" style="color: #071922; text-decoration: underline;">{task.get('email', 'N/A')}</a></td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">Osoite</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">{task.get('osoite', 'N/A')}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">Tilattu</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">{task.get('created_at', 'N/A')[:16]}</td>
                                </tr>
                            </table>

                            <!-- Simulaatio -->
                            <p style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #6B7280; margin: 0 0 8px 0;">Simulaatio</p>
                            <table role="presentation" cellpadding="0" cellspacing="0" style="width: 100%; margin: 0 0 24px 0;">
                                {status_row}
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">Hilaresolaatio</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">{resolution} m</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">WDR-analyysi</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">{wdr}</td>
                                </tr>
                            </table>

                            <!-- Tulokset -->
                            <p style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #6B7280; margin: 0 0 8px 0;">Tulokset</p>
                            <p style="margin: 0 0 8px 0;"><a href="{results_url}" style="color: #44E3A7; font-size: 14px; text-decoration: underline;">{results_url}</a></p>

                            {action_section}
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #F1F1F2; padding: 24px 40px; text-align: center;">
                            <p style="margin: 0; font-size: 12px; color: #9CA3AF;">Automaattinen QA-ilmoitus &middot; Loopshore</p>
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
    body_text = f"""MIKROILMASTOANALYYSI – QA-TARKISTUS

ASIAKAS
Nimi:     {task.get('nimi', 'N/A')}
Email:    {task.get('email', 'N/A')}
Osoite:   {task.get('osoite', 'N/A')}
Tilattu:  {task.get('created_at', 'N/A')[:16]}

SIMULAATIO
Status:         {'Onnistui' if success else 'Epäonnistui'}
{'Kesto:          ' + str(duration_min) + ' min' if success else 'Virhe:          ' + error_msg}
Hilaresolaatio: {resolution} m
WDR-analyysi:   {wdr}

TULOKSET
{results_url}

TOIMENPIDE
Hyväksy: {approve_url}
Hylkää:  {reject_url}

Linkit voimassa {expires_str}.
Hyväksyntä lähettää asiakkaalle automaattisesti linkin tuloksiin.

--
Automaattinen QA-ilmoitus / Loopshore
"""

    if dry_run:
        logger.info("[DRY-RUN] Would send QA notification:")
        logger.info(f"  To: {', '.join(QA_RECIPIENTS)}")
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
        message["To"] = ", ".join(QA_RECIPIENTS)

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

        logger.info(f"QA notification sent to: {', '.join(QA_RECIPIENTS)}")
        return True

    except Exception as e:
        logger.error(f"Failed to send QA notification: {e}")
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

    success = send_qa_notification(task, dry_run=args.dry_run)
    sys.exit(0 if success else 1)
