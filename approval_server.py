#!/usr/bin/env python3
"""
Mikroilmastoanalyysi - Approval Server

Web-palvelin joka käsittelee QA-hyväksynnät ja hylkäykset.
Janne ja Tuomas voivat klikata linkkejä emailissa hyväksyäkseen/hylätäkseen analyysit.
"""

from flask import Flask, render_template_string, request
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
import sys

# Lisää projekti polkuun
sys.path.insert(0, str(Path(__file__).parent))

# Konfiguraatio
TASKS_FILE = Path("/home/eetu/apps/email_manager/data/mikroilmasto_tasks.json")
PORT = 8082

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# HTML Templates
APPROVE_SUCCESS_TEMPLATE = """
<!DOCTYPE html>
<html lang="fi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Analyysi hyväksytty</title>
    <style>
        body {
            font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #F1F1F2;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            color: #071922;
        }
        .logo {
            margin-bottom: 24px;
        }
        .card {
            background: white;
            border-radius: 8px;
            padding: 48px;
            max-width: 460px;
            width: 100%;
        }
        .status-bar {
            width: 48px;
            height: 4px;
            background: #44E3A7;
            border-radius: 2px;
            margin-bottom: 24px;
        }
        h1 {
            font-size: 22px;
            font-weight: 600;
            margin: 0 0 24px 0;
        }
        .label {
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: #6B7280;
            margin: 0 0 4px 0;
        }
        .value {
            font-size: 15px;
            margin: 0 0 16px 0;
        }
        .meta {
            border-top: 1px solid #E8E8E8;
            padding-top: 24px;
            margin-top: 24px;
            font-size: 13px;
            color: #6B7280;
            line-height: 1.6;
        }
    </style>
</head>
<body>
    <img class="logo" src="https://microclimateanalysis.com/assets/loopshore-logo-dark.png" alt="Loopshore" width="180" style="width: 180px; height: auto;">
    <div class="card">
        <div class="status-bar"></div>
        <h1>Analyysi hyväksytty</h1>
        <p class="label">Asiakas</p>
        <p class="value">{{ task.nimi }}</p>
        <p class="label">Osoite</p>
        <p class="value">{{ task.osoite }}</p>
        <p class="label">Hyväksyjä</p>
        <p class="value">{{ approver }}</p>
        <div class="meta">
            Asiakkaalle on lähetetty automaattisesti linkki tuloksiin.<br>
            Linkki voimassa 30 päivää.
        </div>
    </div>
</body>
</html>
"""

REJECT_SUCCESS_TEMPLATE = """
<!DOCTYPE html>
<html lang="fi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Analyysi hylätty</title>
    <style>
        body {
            font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #F1F1F2;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            color: #071922;
        }
        .logo {
            margin-bottom: 24px;
        }
        .card {
            background: white;
            border-radius: 8px;
            padding: 48px;
            max-width: 460px;
            width: 100%;
        }
        .status-bar {
            width: 48px;
            height: 4px;
            background: #D1D5DB;
            border-radius: 2px;
            margin-bottom: 24px;
        }
        h1 {
            font-size: 22px;
            font-weight: 600;
            margin: 0 0 24px 0;
        }
        .label {
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: #6B7280;
            margin: 0 0 4px 0;
        }
        .value {
            font-size: 15px;
            margin: 0 0 16px 0;
        }
        .meta {
            border-top: 1px solid #E8E8E8;
            padding-top: 24px;
            margin-top: 24px;
            font-size: 13px;
            color: #6B7280;
            line-height: 1.6;
        }
    </style>
</head>
<body>
    <img class="logo" src="https://microclimateanalysis.com/assets/loopshore-logo-dark.png" alt="Loopshore" width="180" style="width: 180px; height: auto;">
    <div class="card">
        <div class="status-bar"></div>
        <h1>Analyysi hylätty</h1>
        <p class="label">Asiakas</p>
        <p class="value">{{ task.nimi }}</p>
        <p class="label">Osoite</p>
        <p class="value">{{ task.osoite }}</p>
        <p class="label">Hylkääjä</p>
        <p class="value">{{ approver }}</p>
        <div class="meta">
            Asiakkaalle ei lähetetä ilmoitusta.<br>
            Analyysi jää sisäiseen arkistoon.
        </div>
    </div>
</body>
</html>
"""

ERROR_TEMPLATE = """
<!DOCTYPE html>
<html lang="fi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <style>
        body {
            font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #F1F1F2;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
            color: #071922;
        }
        .logo {
            margin-bottom: 24px;
        }
        .card {
            background: white;
            border-radius: 8px;
            padding: 48px;
            max-width: 460px;
            width: 100%;
            text-align: center;
        }
        .status-bar {
            width: 48px;
            height: 4px;
            background: #D1D5DB;
            border-radius: 2px;
            margin: 0 auto 24px auto;
        }
        h1 {
            font-size: 22px;
            font-weight: 600;
            margin: 0 0 16px 0;
        }
        p {
            color: #6B7280;
            line-height: 1.6;
            margin: 0;
            font-size: 15px;
        }
    </style>
</head>
<body>
    <img class="logo" src="https://microclimateanalysis.com/assets/loopshore-logo-dark.png" alt="Loopshore" width="180" style="width: 180px; height: auto;">
    <div class="card">
        <div class="status-bar"></div>
        <h1>{{ title }}</h1>
        <p>{{ message }}</p>
    </div>
</body>
</html>
"""


def load_tasks():
    """Lataa tehtävälista."""
    if not TASKS_FILE.exists():
        return {"tasks": [], "last_updated": None}

    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tasks(data):
    """Tallenna tehtävälista."""
    data["last_updated"] = datetime.now().isoformat()

    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_task_by_uuid(uuid):
    """Etsi tehtävä UUID:n perusteella."""
    data = load_tasks()
    for task in data["tasks"]:
        if task.get("simulation_uuid") == uuid:
            return task, data
    return None, data


def get_approver_email():
    """Hae hyväksyjän email IP-osoitteesta tai headerista."""
    # Tässä voidaan myöhemmin lisätä IP-pohjainen tunnistus
    # Nyt palautetaan vain "QA Team"
    return request.headers.get('X-Forwarded-For', request.remote_addr)


@app.route('/')
def index():
    """Pääsivu."""
    return render_template_string(ERROR_TEMPLATE,
        title="Mikroilmastoanalyysi - Approval System",
        message="Tämä on hyväksyntäjärjestelmän endpoint. Käytä linkkejä emailissa."
    )


@app.route('/approve/<uuid>/<token>')
def approve(uuid, token):
    """Hyväksy analyysi."""
    logger.info(f"Approval request: {uuid}")

    task, data = find_task_by_uuid(uuid)

    if not task:
        logger.error(f"Task not found: {uuid}")
        return render_template_string(ERROR_TEMPLATE,
            title="Tehtävää ei löydy",
            message="Tehtävää ei löytynyt järjestelmästä. Se on ehkä jo käsitelty."
        ), 404

    # Tarkista token
    if task.get("qa_approval_token") != token:
        logger.error(f"Invalid token for task: {uuid}")
        return render_template_string(ERROR_TEMPLATE,
            title="Virheellinen token",
            message="Hyväksyntälinkki on virheellinen."
        ), 403

    # Tarkista että token ei ole vanhentunut
    expires_at = task.get("qa_approval_expires_at")
    if expires_at:
        expires_dt = datetime.fromisoformat(expires_at)
        if datetime.now() > expires_dt:
            logger.error(f"Token expired for task: {uuid}")
            return render_template_string(ERROR_TEMPLATE,
                title="Linkki vanhentunut",
                message=f"Hyväksyntälinkki vanheni {expires_dt.strftime('%d.%m.%Y %H:%M')}. Ota yhteyttä ylläpitoon."
            ), 410

    # Hyväksy
    approver = get_approver_email()
    task["status"] = "approved"
    task["qa_approved_by"] = approver
    task["qa_approved_at"] = datetime.now().isoformat()

    # Aseta asiakkaan linkin vanhentuminen (30 päivää)
    task["customer_link_expires_at"] = (datetime.now() + timedelta(days=30)).isoformat()

    save_tasks(data)

    logger.info(f"Task approved: {uuid} by {approver}")

    # Lähetä asiakkaalle email
    try:
        from send_customer_email import send_customer_email
        send_customer_email(task)

        # Merkitse lähetetyksi
        task["status"] = "completed"
        task["customer_notification_sent_at"] = datetime.now().isoformat()
        save_tasks(data)

        logger.info(f"Customer email sent for task: {uuid}")
    except Exception as e:
        logger.error(f"Failed to send customer email: {e}")
        # Hyväksyntä on silti tehty, vaikka email epäonnistuisi

    return render_template_string(APPROVE_SUCCESS_TEMPLATE, task=task, approver=approver)


@app.route('/reject/<uuid>/<token>')
def reject(uuid, token):
    """Hylkää analyysi."""
    logger.info(f"Reject request: {uuid}")

    task, data = find_task_by_uuid(uuid)

    if not task:
        logger.error(f"Task not found: {uuid}")
        return render_template_string(ERROR_TEMPLATE,
            title="Tehtävää ei löydy",
            message="Tehtävää ei löytynyt järjestelmästä."
        ), 404

    # Tarkista token (sama kuin approve)
    if task.get("qa_approval_token") != token:
        logger.error(f"Invalid token for task: {uuid}")
        return render_template_string(ERROR_TEMPLATE,
            title="Virheellinen token",
            message="Hylkäyslinkki on virheellinen."
        ), 403

    # Hylkää
    approver = get_approver_email()
    task["status"] = "rejected"
    task["qa_approved_by"] = approver
    task["qa_approved_at"] = datetime.now().isoformat()

    save_tasks(data)

    logger.info(f"Task rejected: {uuid} by {approver}")

    return render_template_string(REJECT_SUCCESS_TEMPLATE, task=task, approver=approver)


@app.route('/status/<uuid>')
def status(uuid):
    """Näytä tehtävän status (debug)."""
    task, _ = find_task_by_uuid(uuid)

    if not task:
        return {"error": "Task not found"}, 404

    return {
        "uuid": uuid,
        "status": task.get("status"),
        "customer": task.get("nimi"),
        "address": task.get("osoite"),
        "qa_approved_by": task.get("qa_approved_by"),
        "qa_approved_at": task.get("qa_approved_at"),
    }


if __name__ == "__main__":
    logger.info(f"Starting Approval Server on port {PORT}")
    logger.info(f"Tasks file: {TASKS_FILE}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
