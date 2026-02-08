# Mikroilmastoanalyysi - Täysi automaatio

Automaattinen emailien haku ja simulaatioiden käynnistys.

## ⚡ Pikaohjeet

### 1. Testaa ensin
```bash
cd /home/eetu/apps/CFD_Microclimate/automation
bash test_automation.sh
```

### 2. Asenna automatisointi
```bash
bash setup_full_automation.sh
```

**Valmis!** Järjestelmä käynnistää simulaatiot automaattisesti 5-15min emailin saapumisen jälkeen.

## Workflow

```
Email tilaus
    ↓
fetch_mikroilmasto_emails.py (käynnistetään manuaalisesti tai cronilla)
    ↓
mikroilmasto_tasks.json (status: pending)
    ↓
process_simulation_queue.py (cron: joka tunti)
    ↓
CFD-simulaatio suoritetaan
    ↓
Tulokset kopioidaan → /srv/simulations/<uuid>/
    ↓
Asiakas voi ladata tulokset: https://microclimateanalysis.com/<uuid>/
```

## Asennus

### 1. Asenna cron-job

```bash
cd /home/eetu/apps/CFD_Microclimate/automation
bash setup_cron.sh
```

Tämä luo cron-jobin joka:
- Ajaa `process_simulation_queue.py` **tunnin välein**
- Prosessoi **max 1 tehtävän** kerralla
- Kirjaa lokit: `automation/logs/queue_processor.log`

### 2. Tarkista että cron on käynnissä

```bash
# Näytä cron-jobit
crontab -l

# Tarkista että cron-daemon pyörii
systemctl status cron
```

## Manuaalinen käyttö

### Testaa ilman muutoksia (dry-run)

```bash
cd /home/eetu/apps/CFD_Microclimate
python3 process_simulation_queue.py --dry-run
```

### Prosessoi yksi tehtävä

```bash
python3 process_simulation_queue.py --max-tasks 1
```

### Prosessoi kaikki pending-tehtävät

```bash
python3 process_simulation_queue.py
```

## Logien seuranta

### Seuraa jonon prosessoijaa reaaliajassa

```bash
tail -f /home/eetu/apps/CFD_Microclimate/automation/logs/queue_processor.log
```

### Katso viimeisimmät 50 riviä

```bash
tail -50 /home/eetu/apps/CFD_Microclimate/automation/logs/queue_processor.log
```

## Tiedostot

| Tiedosto | Kuvaus |
|----------|--------|
| `process_simulation_queue.py` | Pääskripti jonon prosessointiin |
| `setup_cron.sh` | Asentaa cron-jobin |
| `logs/queue_processor.log` | Cron-ajojen lokit |

## Tehtävien tilat (task status)

| Status | Kuvaus |
|--------|--------|
| `pending` | Odottaa käsittelyä |
| `processing` | Simulaatio käynnissä |
| `completed` | Valmis, tulokset kopioitu |
| `failed` | Virhe simulaatiossa |

## Email-integraatio

Email-tilausten hakeminen:

```bash
cd /home/eetu/apps/email_manager
python3 fetch_mikroilmasto_emails.py
```

Voit myös automatisoida tämän cronilla (esim. 15min välein):

```bash
# Lisää crontab:iin
*/15 * * * * cd /home/eetu/apps/email_manager && python3 fetch_mikroilmasto_emails.py >> logs/email_fetch.log 2>&1
```

## Vianmääritys

### Cron ei toimi

```bash
# Tarkista cron-daemon
systemctl status cron
sudo systemctl start cron

# Tarkista cron-jobin syntaksi
crontab -l

# Testaa skripti manuaalisesti
cd /home/eetu/apps/CFD_Microclimate
python3 process_simulation_queue.py --dry-run
```

### Simulaatio epäonnistuu

```bash
# Tarkista lokit
tail -100 automation/logs/queue_processor.log

# Testaa CFD-simulaatio manuaalisesti
./run_cfd.sh --geometry examples/u_shaped_courtyard.json --output test_output/
```

### Task jää jumiin "processing" tilaan

Muokkaa manuaalisesti `/home/eetu/apps/email_manager/data/mikroilmasto_tasks.json`:

```json
{
  "status": "pending"  // Vaihda takaisin pending
}
```

## Poista automatisointi

### Poista cron-job

```bash
crontab -e
# Poista rivi jossa on "process_simulation_queue.py"
```

TAI:

```bash
crontab -l | grep -v "process_simulation_queue.py" | crontab -
```

## Optimointi

### Nopea prosessointi (useita tehtäviä kerralla)

Muokkaa cron-job:
```bash
crontab -e

# Muuta:
0 * * * * ... --max-tasks 1

# Arvoon:
0 * * * * ... --max-tasks 5  # Prosessoi 5 tehtävää kerralla
```

### Useammin (esim. 30min välein)

```bash
crontab -e

# Muuta:
0 * * * *    # Joka tunti

# Arvoon:
*/30 * * * * # Joka 30min
```

## Arvioitu käsittelyaika

- **Geometrian luonti** (osm_fetch.py): ~30s - 2min
- **CFD-simulaatio** (run_cfd.sh): ~10min - 1h (riippuu alueen koosta)
- **Tulosten kopiointi**: ~5-10s

**Yhteensä per tehtävä:** ~15min - 1.5h

Jos prosessoit 1 tehtävän/tunti → **~10-20 tehtävää/vrk**
