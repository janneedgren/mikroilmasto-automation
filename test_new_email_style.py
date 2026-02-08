#!/usr/bin/env python3
"""
Testaa uutta Loopshore-tyyliä lähettämällä molemmat emailit Jannelle.

Käyttö:
    cd /home/eetu/apps/CFD_Microclimate
    .venv/bin/python3 test_new_email_style.py
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta

# Gmail API
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import base64

EMAIL_CREDENTIALS = Path("/home/eetu/apps/email_manager/config/email_credentials.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TEST_RECIPIENT = "janne.edgren@loopshore.com"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_email(subject: str, body_html: str, body_text: str) -> bool:
    """Lähetä testiemail."""
    try:
        creds = Credentials.from_authorized_user_file(str(EMAIL_CREDENTIALS), SCOPES)
        service = build("gmail", "v1", credentials=creds)

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["To"] = TEST_RECIPIENT

        message.attach(MIMEText(body_text, "plain", "utf-8"))
        message.attach(MIMEText(body_html, "html", "utf-8"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        service.users().messages().send(userId="me", body={"raw": raw}).execute()

        logger.info(f"Sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed: {e}")
        return False


def test_customer_email():
    """Testaa asiakasemailia."""
    customer_name = "Matti Meikäläinen"
    address = "Mannerheimintie 10, 00100 Helsinki"
    results_url = "https://microclimateanalysis.com/results/test-uuid-123/"
    expires_str = (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y")

    subject = f"[TESTI] Mikroilmastoanalyysi valmis – {address[:50]}"

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

    return send_email(subject, body_html, body_text)


def test_qa_notification():
    """Testaa QA-notifikaatiota."""
    task = {
        "nimi": "Matti Meikäläinen",
        "email": "matti@example.com",
        "osoite": "Mannerheimintie 10, 00100 Helsinki",
        "created_at": "2026-02-08T10:30:00",
        "simulation_uuid": "test-uuid-123",
        "status": "completed",
        "simulation_parameters": {"resolution": "1.0", "wdr_enabled": True},
        "simulation_duration_seconds": 1847,
    }

    results_url = "https://microclimateanalysis.com/results/test-uuid-123/"
    approve_url = "https://microclimateanalysis.com/approve/test-uuid-123/test-token"
    reject_url = "https://microclimateanalysis.com/reject/test-uuid-123/test-token"
    expires_str = (datetime.now() + timedelta(days=7)).strftime("%d.%m.%Y klo %H:%M")
    duration_min = round(1847 / 60, 1)

    subject = f"[TESTI] QA-tarkistus: {task['osoite'][:50]}"

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
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">{task['nimi']}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">Email</td>
                                    <td style="padding: 8px 0; font-size: 14px;"><a href="mailto:{task['email']}" style="color: #071922; text-decoration: underline;">{task['email']}</a></td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">Osoite</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">{task['osoite']}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">Tilattu</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">{task['created_at'][:16]}</td>
                                </tr>
                            </table>

                            <!-- Simulaatio -->
                            <p style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #6B7280; margin: 0 0 8px 0;">Simulaatio</p>
                            <table role="presentation" cellpadding="0" cellspacing="0" style="width: 100%; margin: 0 0 24px 0;">
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280; width: 140px;">Status</td>
                                    <td style="padding: 8px 0; font-size: 14px; font-weight: 600; color: #071922;">Onnistui</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">Kesto</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">{duration_min} min</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">Hilaresolaatio</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">1.0 m</td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 0; font-size: 13px; color: #6B7280;">WDR-analyysi</td>
                                    <td style="padding: 8px 0; font-size: 14px; color: #071922;">Kyllä</td>
                                </tr>
                            </table>

                            <!-- Tulokset -->
                            <p style="font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: #6B7280; margin: 0 0 8px 0;">Tulokset</p>
                            <p style="margin: 0 0 8px 0;"><a href="{results_url}" style="color: #44E3A7; font-size: 14px; text-decoration: underline;">{results_url}</a></p>

                            <!-- Viiva -->
                            <div style="border-top: 1px solid #E8E8E8; margin: 24px 0 0 0;"></div>

                            <!-- Painikkeet -->
                            <table role="presentation" cellpadding="0" cellspacing="0" style="margin: 24px 0;">
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

                            <!-- Huomautus -->
                            <p style="font-size: 12px; color: #9CA3AF; margin: 0;">Hyväksyntä lähettää asiakkaalle automaattisesti linkin tuloksiin. Linkit voimassa {expires_str}.</p>
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

    body_text = f"""MIKROILMASTOANALYYSI - QA-TARKISTUS

ASIAKAS
Nimi:     {task['nimi']}
Email:    {task['email']}
Osoite:   {task['osoite']}
Tilattu:  {task['created_at'][:16]}

SIMULAATIO
Status:         Onnistui
Kesto:          {duration_min} min
Hilaresolaatio: 1.0 m
WDR-analyysi:   Kyllä

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

    return send_email(subject, body_html, body_text)


if __name__ == "__main__":
    print("Lähetetään testeilemailit uudella Loopshore-tyylillä...")
    print(f"Vastaanottaja: {TEST_RECIPIENT}")
    print()

    ok1 = test_customer_email()
    print(f"  Asiakasemail: {'OK' if ok1 else 'EPÄONNISTUI'}")

    ok2 = test_qa_notification()
    print(f"  QA-ilmoitus:  {'OK' if ok2 else 'EPÄONNISTUI'}")

    print()
    if ok1 and ok2:
        print("Molemmat testeilemailit lähetetty!")
    else:
        print("Jokin epäonnistui, tarkista logit.")
        sys.exit(1)
