# Systemd Services - Automaattinen käynnistys

Nämä palvelut käynnistyvät automaattisesti koneen käynnistyessä (esim. sähkökatkon jälkeen).

## Asennus

```bash
cd /home/eetu/apps/CFD_Microclimate/systemd
sudo bash INSTALL_SERVICES.sh
```

Tämä asentaa ja käynnistää:
1. **cfd-results-server.service** - HTTP-palvelin (port 8080)
2. **cloudflared.service** - Cloudflare Tunnel

## Käyttökomennot

### Tilan tarkistus
```bash
# HTTP-palvelin
sudo systemctl status cfd-results-server

# Cloudflare Tunnel
sudo systemctl status cloudflared

# Molemmat kerralla
systemctl status cfd-results-server cloudflared
```

### Käynnistä/Pysäytä/Käynnistä uudelleen
```bash
# Käynnistä
sudo systemctl start cfd-results-server
sudo systemctl start cloudflared

# Pysäytä
sudo systemctl stop cfd-results-server
sudo systemctl stop cloudflared

# Käynnistä uudelleen
sudo systemctl restart cfd-results-server
sudo systemctl restart cloudflared
```

### Ota käyttöön/Poista käytöstä automaattinen käynnistys
```bash
# Ota käyttöön (käynnistyy automaattisesti bootissa)
sudo systemctl enable cfd-results-server
sudo systemctl enable cloudflared

# Poista käytöstä
sudo systemctl disable cfd-results-server
sudo systemctl disable cloudflared
```

### Logit
```bash
# Näytä viimeisimmät logit
sudo journalctl -u cfd-results-server -n 50
sudo journalctl -u cloudflared -n 50

# Seuraa logeja reaaliajassa (live)
sudo journalctl -u cfd-results-server -f
sudo journalctl -u cloudflared -f

# Molemmat kerralla
sudo journalctl -u cfd-results-server -u cloudflared -f
```

## Automaattinen uudelleenkäynnistys

Palvelut on konfiguroitu käynnistymään uudelleen automaattisesti jos ne kaatuvat:
- `Restart=always` - Käynnistää uudelleen aina kun prosessi päättyy
- `RestartSec=10` - Odottaa 10 sekuntia ennen uudelleenkäynnistystä

## Testaa automaattista käynnistystä

```bash
# Simuloi sähkökatko (käynnistä kone uudelleen)
sudo reboot

# Kun kone on käynnistynyt, tarkista että palvelut ovat käynnissä:
systemctl status cfd-results-server cloudflared
```

## Poista palvelut

Jos haluat poistaa palvelut:

```bash
# Pysäytä palvelut
sudo systemctl stop cfd-results-server cloudflared

# Poista automaattinen käynnistys
sudo systemctl disable cfd-results-server cloudflared

# Poista service-tiedostot
sudo rm /etc/systemd/system/cfd-results-server.service
sudo rm /etc/systemd/system/cloudflared.service

# Päivitä systemd
sudo systemctl daemon-reload
```

## Tiedostojen sijainnit

- Service-tiedostot: `/etc/systemd/system/`
- Config: `/home/eetu/.cloudflared/config.yml`
- Python-palvelin: `/home/eetu/apps/CFD_Microclimate/serve_results.py`
- Logit: `journalctl` (systemd journal)

## Vianmääritys

### Palvelu ei käynnisty

```bash
# Tarkista virheviestit
sudo systemctl status cfd-results-server
sudo journalctl -u cfd-results-server -n 50

# Testaa palvelin manuaalisesti
cd /home/eetu/apps/CFD_Microclimate
python3 serve_results.py
```

### Portti käytössä

```bash
# Tarkista mikä käyttää porttia 8080
sudo lsof -i :8080
sudo netstat -tlnp | grep 8080

# Tapa prosessi
sudo fuser -k 8080/tcp
```

### Päivitä service-tiedostot

Jos muokkaat service-tiedostoja:

```bash
# Kopioi päivitetyt tiedostot
sudo cp systemd/*.service /etc/systemd/system/

# Päivitä systemd
sudo systemctl daemon-reload

# Käynnistä palvelut uudelleen
sudo systemctl restart cfd-results-server cloudflared
```
