# Mikroilmastoanalyysi - Järjestelmäkaavio

**Viimeksi päivitetty:** 2026-02-08

---

## 🎯 Täysi workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         1. TILAUS                                    │
│  Asiakas täyttää Google Formsin → Email lähtee Gmail:iin           │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   2. EMAIL FETCH (Cron :00 UTC)                      │
│  Script: fetch_mikroilmasto_emails.py                               │
│  • Lukee Gmail API:lla uudet emailit                                │
│  • Parsii: nimi, email, osoite                                      │
│  • Luo UUID jokaiselle tilaukselle                                  │
│  • Tallentaa: mikroilmasto_tasks.json (status: "pending")           │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│              3. QUEUE PROCESSOR (Cron :05 UTC)                       │
│  Script: process_simulation_queue.py                                │
│                                                                      │
│  VAIHE 1: Luo geometria                                             │
│  • osm_fetch.py --address "Osoite" → geometria.json                │
│  • Hakee OpenStreetMap-data (rakennukset, tiet)                    │
│                                                                      │
│  VAIHE 2: Suorita CFD-simulaatio                                    │
│  • run_cfd.sh --geometry geometria.json --output results/           │
│  • OpenFOAM: SIMPLE-algoritmi, k-ω SST turbulenssi                 │
│  • Kesto: 30-120 min (riippuu alueesta)                            │
│                                                                      │
│  VAIHE 3: Kopioi tulokset                                           │
│  • results/analysis/ → /srv/simulations/<UUID>/                     │
│                                                                      │
│  VAIHE 4: Generoi QA-token                                          │
│  • secrets.token_urlsafe(32) → 256-bit random token                │
│  • Voimassa 7 päivää                                                │
│                                                                      │
│  VAIHE 5: Päivitä status                                            │
│  • status: "pending" → "processing" → "pending_approval"            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 4. QA NOTIFICATION EMAIL                             │
│  Script: send_qa_notification.py                                    │
│  Vastaanottajat: janne.edgren@loopshore.com                        │
│                  tuomas.alinikula@loopshore.com                     │
│                                                                      │
│  Emailin sisältö:                                                   │
│  • Asiakastiedot (nimi, email, osoite)                             │
│  • Simulaatioparametrit (resoluutio, kesto)                        │
│  • Linkki tuloksiin                                                 │
│  • HYVÄKSY-nappi → microclimateanalysis.com/approve/<UUID>/<TOKEN> │
│  • HYLKÄÄ-nappi → microclimateanalysis.com/reject/<UUID>/<TOKEN>   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                    Janne/Tuomas klikkaa HYVÄKSY
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                5. APPROVAL SERVER (Flask, port 8082)                 │
│  Script: approval_server.py                                         │
│                                                                      │
│  @app.route('/approve/<uuid>/<token>')                              │
│  • Validoi UUID ja token                                            │
│  • Tarkista voimassaolo (max 7 päivää)                             │
│  • Päivitä status: "pending_approval" → "approved"                  │
│  • Kutsu: send_customer_email(task)                                 │
│  • Päivitä status: "approved" → "completed"                         │
│  • Näytä success-sivu                                               │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│               6. CUSTOMER EMAIL                                      │
│  Script: send_customer_email.py                                     │
│  Vastaanottaja: Asiakkaan email                                     │
│                                                                      │
│  Emailin sisältö:                                                   │
│  • "Analyysisi on valmis!"                                          │
│  • Linkki: https://microclimateanalysis.com/<UUID>/                │
│  • Sisältö: PDF-raportit, PNG-kuvat, WDR-analyysi                  │
│  • Voimassa: 30 päivää                                              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🌐 Web-palvelut

### Cloudflare Tunnel Routing

```
microclimateanalysis.com
  │
  ├─ /approve/<uuid>/<token>  ──→  localhost:8082 (approval_server.py)
  ├─ /reject/<uuid>/<token>   ──→  localhost:8082 (approval_server.py)
  ├─ /status/<uuid>           ──→  localhost:8082 (approval_server.py)
  └─ /*                       ──→  localhost:8080 (serve_results.py)
```

### Port 8080 - Results Server
**Script:** `serve_results.py`
**Tyyppi:** Python HTTP server
**Käyttö:** Staattisten tulosten jako

```
GET /
  → Index page (lista projekteista)

GET /<uuid>/
  → Asiakkaan tulossivu
  → PDF-raportit, PNG-kuvat, HTML-dashboardit
```

### Port 8082 - Approval Server
**Script:** `approval_server.py`
**Tyyppi:** Flask web application
**Käyttö:** QA-hyväksyntä ja hylkäys

```
GET /approve/<uuid>/<token>
  → Hyväksy analyysi
  → Lähetä asiakasemail
  → Näytä success-sivu

GET /reject/<uuid>/<token>
  → Hylkää analyysi
  → Päivitä status: "rejected"
  → Näytä rejection-sivu

GET /status/<uuid>
  → Näytä tilanne (JSON tai HTML)
```

---

## 💾 Tiedostot ja hakemistot

### Tehtäväjono

**Tiedosto:** `/home/eetu/apps/email_manager/data/mikroilmasto_tasks.json`

```json
{
  "tasks": [
    {
      "simulation_uuid": "a1b2c3d4-...",
      "nimi": "Matti Meikäläinen",
      "email": "matti@example.com",
      "osoite": "Mannerheimintie 1, Helsinki",
      "status": "pending_approval",
      "created_at": "2026-02-08T12:00:00",
      "simulation_started_at": "2026-02-08T12:05:00",
      "simulation_completed_at": "2026-02-08T13:20:00",
      "simulation_duration_seconds": 4500,
      "simulation_directory": "/srv/simulations/a1b2c3d4-.../",
      "results_url": "https://microclimateanalysis.com/a1b2c3d4-.../",
      "qa_approval_token": "AbC123...",
      "qa_approval_expires_at": "2026-02-15T13:20:00",
      "qa_notification_sent_at": "2026-02-08T13:21:00",
      "simulation_parameters": {
        "resolution": 1.0,
        "wdr_enabled": true,
        "wind_directions": 8
      }
    }
  ],
  "last_updated": "2026-02-08T13:21:00"
}
```

### Tuloshakemistot

```
/srv/simulations/
  └── <UUID>/
      ├── analysis/
      │   ├── domain_N.png         # Tuulikentät (N/NE/E/SE/S/SW/W/NW)
      │   ├── domain_N.pdf
      │   ├── wind_rose.png
      │   ├── wdr_analysis.png
      │   ├── wdr_analysis.pdf
      │   ├── report.html
      │   └── metadata.json
      └── [muut tiedostot]
```

---

## 🔄 Status-siirtymät

### Onnistunut simulaatio

```
pending
  ↓ (queue processor starts)
processing
  ↓ (simulation completes)
pending_approval
  ↓ (Janne/Tuomas clicks HYVÄKSY)
approved
  ↓ (customer email sent)
completed
```

### Epäonnistunut simulaatio

```
pending
  ↓ (queue processor starts)
processing
  ↓ (error occurs)
failed
  ↓ (QA notification sent)
  ↓ (Janne/Tuomas clicks HYLKÄÄ)
rejected
```

### Hylätty simulaatio

```
pending
  ↓
processing
  ↓
pending_approval
  ↓ (Janne/Tuomas clicks HYLKÄÄ)
rejected
```

---

## ⚙️ Systemd-palvelut

### cfd-results-server.service

```ini
[Unit]
Description=Mikroilmastoanalyysi Results Server

[Service]
Type=simple
User=eetu
WorkingDirectory=/home/eetu/apps/CFD_Microclimate
ExecStart=/usr/bin/python3 serve_results.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**Status:** Automaattinen käynnistys rebootin jälkeen ✅

### approval-server.service

```ini
[Unit]
Description=Mikroilmastoanalyysi Approval Server

[Service]
Type=simple
User=eetu
WorkingDirectory=/home/eetu/apps/CFD_Microclimate
ExecStart=/home/eetu/apps/CFD_Microclimate/.venv/bin/python3 approval_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**Status:** Automaattinen käynnistys rebootin jälkeen ✅

### cloudflared.service

```ini
[Unit]
Description=Cloudflare Tunnel

[Service]
Type=simple
User=eetu
ExecStart=/usr/bin/cloudflared --config /home/eetu/.cloudflared/config.yml tunnel run simulations
Restart=always

[Install]
WantedBy=multi-user.target
```

**Status:** Automaattinen käynnistys rebootin jälkeen ✅

---

## 🕐 Cron-ajastimet

### Email Fetch (UTC :00)

```cron
0 * * * * cd /home/eetu/apps/email_manager && /usr/bin/python3 fetch_mikroilmasto_emails.py >> /home/eetu/apps/email_manager/logs/email_fetch.log 2>&1
```

**Toiminto:**
- Hae uudet emailit Gmail API:lla
- Parsii tilaukset
- Tallenna mikroilmasto_tasks.json
- Status: `pending`

**Seuraava ajo:** Joka tunti :00 (UTC)

### Queue Processor (UTC :05)

```cron
5 * * * * cd /home/eetu/apps/CFD_Microclimate && /usr/bin/python3 process_simulation_queue.py --max-tasks 1 >> /home/eetu/apps/CFD_Microclimate/automation/logs/queue_processor.log 2>&1
```

**Toiminto:**
- Prosessoi max 1 tehtävä kerrallaan
- Luo geometria → suorita CFD → kopioi tulokset
- Lähetä QA-notifikaatio
- Status: `pending` → `pending_approval`

**Seuraava ajo:** Joka tunti :05 (UTC)

---

## 🔐 Turvallisuus

### QA Approval Tokens

- **Generaatio:** `secrets.token_urlsafe(32)` (256 bit)
- **Voimassaolo:** 7 päivää
- **Validointi:** approval_server.py tarkistaa:
  - Onko token oikein
  - Onko token vanhentunut
  - Onko task olemassa

### Customer Links

- **URL:** `https://microclimateanalysis.com/<UUID>/`
- **Voimassaolo:** 30 päivää (suositus asiakkaalle)
- **Sisältö:** Staattiset tiedostot (PDF, PNG, HTML)
- **Ei autentikointia** - UUID toimii salaisuutena

---

## 📊 Metriikat ja seuranta

### Lokit

| Loki | Sijainti |
|------|----------|
| Email fetch | `/home/eetu/apps/email_manager/logs/email_fetch.log` |
| Queue processor | `/home/eetu/apps/CFD_Microclimate/automation/logs/queue_processor.log` |
| Results server | `sudo journalctl -u cfd-results-server` |
| Approval server | `sudo journalctl -u approval-server` |
| Cloudflared | `sudo journalctl -u cloudflared` |

### Seurattavat asiat

```bash
# Kuinka monta tehtävää jonossa?
cat /home/eetu/apps/email_manager/data/mikroilmasto_tasks.json | \
  python3 -c "import json,sys; print(len([t for t in json.load(sys.stdin)['tasks'] if t['status']=='pending']))"

# Viimeisin simulaatio?
cat /home/eetu/apps/email_manager/data/mikroilmasto_tasks.json | \
  python3 -c "import json,sys; tasks=json.load(sys.stdin)['tasks']; print(tasks[-1] if tasks else 'No tasks')"

# Palvelut käynnissä?
systemctl is-active cfd-results-server cloudflared approval-server
```

---

## 🚀 Quick Start (uusi serveri)

```bash
# 1. Kopioi varmuuskopio
rsync -avz old-server:/home/eetu/apps/ /home/eetu/apps/
rsync -avz old-server:/home/eetu/.cloudflared/ /home/eetu/.cloudflared/

# 2. Luo hakemistot
sudo mkdir -p /srv/simulations
sudo chown -R eetu:eetu /srv/simulations

# 3. Python-ympäristö
cd /home/eetu/apps/CFD_Microclimate
python3 -m venv .venv
source .venv/bin/activate
pip install flask google-auth google-auth-oauthlib google-api-python-client
deactivate

# 4. Systemd
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cfd-results-server cloudflared approval-server
sudo systemctl start cfd-results-server cloudflared approval-server

# 5. Cron
cd automation
./setup_full_automation.sh

# 6. Testaa
curl http://localhost:8080/
curl http://localhost:8082/
curl https://microclimateanalysis.com/
```

**Valmis!** ✅

---

**Katso lisää:** `/home/eetu/apps/MIKROILMASTO_SYSTEM.md`
