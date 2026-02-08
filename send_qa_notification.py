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
        subject = f"✅ Mikroilmastoanalyysi valmis - QA tarkistus: {task['osoite'][:50]}"
    else:
        subject = f"❌ Mikroilmastoanalyysi epäonnistui: {task['osoite'][:50]}"

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
        status_section = f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #eee; font-weight: bold;">Status:</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; color: #22c55e;">✅ Onnistui</td>
        </tr>
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #eee; font-weight: bold;">Kesto:</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee;">{duration_min} minuuttia</td>
        </tr>
        """

        action_section = f"""
        <h2 style="color: #2c5aa0; margin-top: 32px;">📋 Toimenpide</h2>
        <p style="margin-bottom: 16px;">Tarkista tulokset ja hyväksy tai hylkää:</p>

        <table style="width: 100%; margin-bottom: 24px;">
            <tr>
                <td style="padding: 16px; text-align: center;">
                    <a href="{approve_url}" style="display: inline-block; background: #22c55e; color: white; padding: 16px 32px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
                        ✅ HYVÄKSYN
                    </a>
                </td>
                <td style="padding: 16px; text-align: center;">
                    <a href="{reject_url}" style="display: inline-block; background: #ef4444; color: white; padding: 16px 32px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
                        ❌ HYLKÄÄN
                    </a>
                </td>
            </tr>
        </table>

        <p style="font-size: 14px; color: #666; padding: 16px; background: #f7fafc; border-radius: 8px;">
            <strong>Huom:</strong> Jos hyväksyt, asiakkaalle lähetetään automaattisesti linkki tuloksiin.<br>
            Linkit voimassa: {expires_str}
        </p>
        """
    else:
        status_section = f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #eee; font-weight: bold;">Status:</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; color: #ef4444;">❌ Epäonnistui</td>
        </tr>
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #eee; font-weight: bold;">Virhe:</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee;"><pre style="margin:0; font-size:12px;">{error_msg}</pre></td>
        </tr>
        """

        action_section = f"""
        <h2 style="color: #ef4444; margin-top: 32px;">⚠️ Toimenpide tarvitaan</h2>
        <p>Simulaatio epäonnistui. Voit hylätä tai yrittää uudelleen.</p>

        <table style="width: 100%; margin-bottom: 24px;">
            <tr>
                <td style="padding: 16px; text-align: center;">
                    <a href="{reject_url}" style="display: inline-block; background: #ef4444; color: white; padding: 16px 32px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
                        ❌ HYLKÄÄ
                    </a>
                </td>
            </tr>
        </table>
        """

    body_html = f"""
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 700px; margin: 0 auto;">
    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 32px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: white; margin: 0; font-size: 28px;">Mikroilmastoanalyysi - QA Tarkistus</h1>
    </div>

    <div style="background: white; padding: 32px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px;">
        <h2 style="color: #2c5aa0; margin-top: 0;">👤 Asiakkaan tiedot</h2>
        <table style="border-collapse: collapse; width: 100%; margin-bottom: 24px;">
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #eee; font-weight: bold; width: 180px;">Nimi:</td>
                <td style="padding: 12px; border-bottom: 1px solid #eee;">{task.get('nimi', 'N/A')}</td>
            </tr>
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #eee; font-weight: bold;">Email:</td>
                <td style="padding: 12px; border-bottom: 1px solid #eee;"><a href="mailto:{task.get('email', '')}">{task.get('email', 'N/A')}</a></td>
            </tr>
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #eee; font-weight: bold;">Osoite:</td>
                <td style="padding: 12px; border-bottom: 1px solid #eee;">{task.get('osoite', 'N/A')}</td>
            </tr>
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #eee; font-weight: bold;">Tilattu:</td>
                <td style="padding: 12px; border-bottom: 1px solid #eee;">{task.get('created_at', 'N/A')[:16]}</td>
            </tr>
        </table>

        <h2 style="color: #2c5aa0;">⚙️ Simulaation tiedot</h2>
        <table style="border-collapse: collapse; width: 100%; margin-bottom: 24px;">
            {status_section}
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #eee; font-weight: bold;">Hilaresolaatio:</td>
                <td style="padding: 12px; border-bottom: 1px solid #eee;">{resolution} m</td>
            </tr>
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #eee; font-weight: bold;">WDR-analyysi:</td>
                <td style="padding: 12px; border-bottom: 1px solid #eee;">{wdr}</td>
            </tr>
        </table>

        <h2 style="color: #2c5aa0;">📊 Tulokset</h2>
        <p style="padding: 16px; background: #f7fafc; border-radius: 8px; border-left: 4px solid #667eea;">
            <strong>Linkki:</strong> <a href="{results_url}" style="color: #667eea;">{results_url}</a>
        </p>

        {action_section}

        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 32px 0;">

        <p style="font-size: 12px; color: #888; text-align: center;">
            Tämä on automaattinen ilmoitus Loopshore mikroilmastoanalyysi-järjestelmästä.
        </p>
    </div>
</body>
</html>
"""

    # Plain text fallback
    body_text = f"""
MIKROILMASTOANALYYSI - QA TARKISTUS

ASIAKKAAN TIEDOT:
Nimi:     {task.get('nimi', 'N/A')}
Email:    {task.get('email', 'N/A')}
Osoite:   {task.get('osoite', 'N/A')}
Tilattu:  {task.get('created_at', 'N/A')[:16]}

SIMULAATION TIEDOT:
Status:           {'✅ Onnistui' if success else '❌ Epäonnistui'}
{'Kesto:            ' + str(duration_min) + ' min' if success else 'Virhe:            ' + error_msg}
Hilaresolaatio:   {resolution} m
WDR-analyysi:     {wdr}

TULOKSET:
{results_url}

TOIMENPIDE:
Hyväksy: {approve_url}
Hylkää:  {reject_url}

Linkit voimassa: {expires_str}

Jos hyväksyt, asiakkaalle lähetetään automaattisesti linkki tuloksiin.

---
Loopshore Mikroilmastoanalyysi
Automaattinen ilmoitus
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
