# Mikroilmastoanalyysi - Claude Quick Reference

**Viimeksi päivitetty:** 2026-02-08
**Status:** ✅ Tuotannossa, täysin automaattinen

---

## 📚 Pääsydokumentaatio

- **Täysi järjestelmädokumentaatio:** `/home/eetu/apps/MIKROILMASTO_SYSTEM.md`
- **Pikaohje & vianmääritys:** `/home/eetu/apps/QUICK_REFERENCE.md`
- **Järjestelmäkaavio:** `/home/eetu/apps/CFD_Microclimate/SYSTEM_OVERVIEW.md`

---

## ⚡ Tärkeimmät tiedostot

### Tuotantoskriptit
```
/home/eetu/apps/email_manager/fetch_mikroilmasto_emails.py
/home/eetu/apps/CFD_Microclimate/process_simulation_queue.py
/home/eetu/apps/CFD_Microclimate/approval_server.py
/home/eetu/apps/CFD_Microclimate/send_qa_notification.py
/home/eetu/apps/CFD_Microclimate/send_customer_email.py
```

### Konfiguraatiot
```
/home/eetu/.cloudflared/config.yml
/home/eetu/.ssh/config (GitHub: janneedgren)
/home/eetu/apps/email_manager/config/email_credentials.json
```

### Systemd-palvelut
```
/etc/systemd/system/cfd-results-server.service    (port 8080)
/etc/systemd/system/approval-server.service        (port 8082)
/etc/systemd/system/cloudflared.service
```

---

## 🔧 Kriittiset asetukset

### URL ja domain
- **Domain:** `microclimateanalysis.com`
- **Tulokset:** `/srv/simulations/<uuid>/`
- **Results server:** Jakaa `/srv/simulations/` portissa 8080

### Python-ympäristöt (TÄRKEÄ!)
```bash
# Email manager - käyttää omaa venv:ää
/home/eetu/apps/email_manager/.venv/bin/python3

# CFD Automation - käyttää omaa venv:ää
/home/eetu/apps/CFD_Microclimate/.venv/bin/python3
```

**Molemmat venv:t sisältävät:**
- Google API libraries (gmail sending)
- Flask (approval server)
- OSM libraries (osmnx, geopandas)

### Cron-ajastukset (UTC!)
```cron
# Email fetch - joka tunti :00
0 * * * * cd /home/eetu/apps/email_manager && \
  /home/eetu/apps/email_manager/.venv/bin/python3 fetch_mikroilmasto_emails.py

# Queue processor - joka tunti :05
5 * * * * cd /home/eetu/apps/CFD_Microclimate && \
  /home/eetu/apps/CFD_Microclimate/.venv/bin/python3 process_simulation_queue.py --max-tasks 1
```

---

## 🚨 Yleisimmät ongelmat

### "Simulaatio epäonnistuu"
→ Tarkista: Käyttääkö cron `.venv/bin/python3`? (EI `/usr/bin/python3`)

### "Email ei lähetä"
→ Tarkista: `/home/eetu/apps/email_manager/config/email_credentials.json`

### "404 tuloksissa"
→ Tarkista: `serve_results.py` jakaa `/srv/simulations/` (EI `results/`)

### "Token MISSING"
→ Korjattu: Token luodaan nyt aina, myös virhetilanteissa

---

## 🔄 Serverin uudelleenrakennus

**Katso täydelliset ohjeet:** `/home/eetu/apps/MIKROILMASTO_SYSTEM.md` § "Asennusohjeet (uusi serveri)"

**Nopea muistilista:**
1. Kopioi `/home/eetu/apps/` ja `/home/eetu/.cloudflared/`
2. Luo `/srv/simulations/` ja aseta oikeudet (`chown eetu:eetu`)
3. Asenna Python venv:t molempiin projekteihin
4. Kopioi `email_credentials.json`
5. Asenna systemd-palvelut
6. Asenna cron-jobit
7. Testaa!

---

## 📊 Workflow-tiivistelmä

```
Google Form → Gmail → Email fetch (cron :00)
  → Task queue JSON → Queue processor (cron :05)
  → OSM geometry → CFD simulation → Results
  → QA notification (Janne + Tuomas)
  → Approval (web link) → Customer email
```

**Katso yksityiskohdat:** `/home/eetu/apps/CFD_Microclimate/SYSTEM_OVERVIEW.md`

---

## 🔑 GitHub-repositoryt

**Owner:** janneedgren
**SSH key:** `/home/eetu/.ssh/id_ed25519_janneedgren`

```
https://github.com/janneedgren/mikroilmasto-email-manager
https://github.com/janneedgren/mikroilmasto-automation
```

**Päivitä GitHubiin:**
```bash
cd /home/eetu/apps/email_manager && git add . && git commit -m "..." && git push
cd /home/eetu/apps/CFD_Microclimate && git add . && git commit -m "..." && git push
```

---

**Tämä on tiivistelmä - katso täysi dokumentaatio MIKROILMASTO_SYSTEM.md:stä!**
