# CFD Mikroilmastosimulointi

Rakennusten ympäristön tuulisuussimulointi SIMPLE-algoritmilla ja turbulenssimalleilla.

## 🚀 Tuotantojärjestelmä (Automated Workflow)

**Täysin automaattinen** email-ohjattu mikroilmastoanalyysijärjestelmä.

### Nopeasti

Järjestelmä on **täysin automaattinen** ja **sähkökatkojen kestävä**. Kaikki palvelut käynnistyvät automaattisesti serverin rebootin jälkeen.

**Katso täydellinen dokumentaatio:** `/home/eetu/apps/MIKROILMASTO_SYSTEM.md`

### Tuotantokomponentit

1. **Email-ohjaus** - `fetch_mikroilmasto_emails.py` (cron: joka tunti :00)
2. **Simulaatioprosessori** - `process_simulation_queue.py` (cron: joka tunti :05)
3. **QA-hyväksyntä** - `approval_server.py` (Flask, port 8082)
4. **Tulospalvelin** - `serve_results.py` (HTTP, port 8080)
5. **Cloudflare Tunnel** - `microclimateanalysis.com`

### Pika-asennus uudelle serverille

```bash
# 1. Asenna systemd-palvelut
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cfd-results-server cloudflared approval-server
sudo systemctl start cfd-results-server cloudflared approval-server

# 2. Asenna cron-ajastimet
cd automation
./setup_full_automation.sh

# 3. Testaa
curl http://localhost:8080/
curl http://localhost:8082/
curl https://microclimateanalysis.com/
```

### Workflow-kaavio

```
Asiakas (Google Form)
  → Gmail API (cron :00)
  → Simulaatio (cron :05)
  → QA-hyväksyntä (Janne + Tuomas)
  → Asiakasemail (automaattinen)
```

**Katso yksityiskohtaiset ohjeet:** `/home/eetu/apps/MIKROILMASTO_SYSTEM.md`

---

## Yleiskatsaus (CFD-solveri)

Projekti tarjoaa työkalut:
- **Tuulikenttien laskentaan** rakennusten ympärillä
- **Tuulisuusvyöhykkeiden** analysointiin (Lawson-kriteerit)
- **Puusuojien** vaikutuksen arviointiin
- **Painekentän** visualisointiin

## Ominaisuudet

- SIMPLE-algoritmi paineen ja nopeuden kytkentään
- Kolme turbulenssimallia: vakio ν_t, k-ε, k-ω SST
- JSON-pohjainen geometriasyöttö
- Numba-optimoitu laskenta suurille hiloille
- Huokoiset esteet (puut, pensaat)

## Asennus

### Vaatimukset
- Python 3.8+
- NumPy
- SciPy
- Matplotlib
- Numba

### Asennus

```bash
pip install -r requirements.txt
```

## Pikaopas

### 1. Simulaatio JSON-tiedostosta

```bash
python main.py --geometry examples/u_shaped_courtyard.json --output results/
```

### 2. Python-käyttö

```python
from solvers.cfd_solver import CFDSolver
from geometry.loader import load_geometry

# Lataa geometria
config = load_geometry('examples/two_buildings.json')

# Luo ratkaisija
solver = CFDSolver.from_config(config)

# Ratkaise
solver.solve()

# Tulokset
velocity = solver.get_velocity_magnitude()
pressure = solver.get_pressure()
```

## Projektin rakenne

```
cfd_microclimate_project/
├── README.md                    # Tämä tiedosto
├── requirements.txt             # Python-riippuvuudet
├── main.py                      # Komentorivikäyttöliittymä
│
├── solvers/                     # Laskentasolverit
│   ├── __init__.py
│   ├── cfd_solver.py           # Pääsolveri (SIMPLE)
│   ├── momentum.py             # Liikemääräyhtälöt
│   ├── pressure.py             # Painekorjaus
│   └── numba_kernels.py        # Numba-optimoidut ytimet
│
├── turbulence_models/           # Turbulenssimallit
│   ├── __init__.py
│   ├── constant.py             # Vakio ν_t
│   ├── k_epsilon.py            # Standard k-ε
│   └── k_omega_sst.py          # k-ω SST (Menter)
│
├── geometry/                    # Geometrian käsittely
│   ├── __init__.py
│   ├── loader.py               # JSON-lukija
│   ├── domain.py               # Laskenta-alue
│   └── obstacles.py            # Esteet (rakennukset, puut)
│
├── boundary_conditions/         # Reunaehdot
│   ├── __init__.py
│   └── boundary.py             # Sisääntulo, ulostulo, seinät
│
├── utils/                       # Apuvälineet
│   ├── __init__.py
│   ├── visualization.py        # Kuvaajat
│   ├── comfort.py              # Tuulisuusvyöhykkeet
│   └── export.py               # Tulosten vienti
│
├── examples/                    # Esimerkkigeometriat (JSON)
│   ├── building_with_tree_shelter.json
│   ├── two_buildings.json
│   ├── four_buildings.json
│   ├── four_buildings_staggered.json
│   └── u_shaped_courtyard.json
│
├── tests/                       # Testit
│   └── test_solver.py
│
├── docs/                        # Dokumentaatio
│   ├── theory.md               # Teoria ja yhtälöt
│   └── turbulence_models.md    # Turbulenssimallien kuvaus
│
└── output/                      # Tuloskansio
```

## Geometriatiedostot (JSON)

### Rakenne

```json
{
  "name": "tapauksen_nimi",
  "description": "Kuvaus",
  "domain": {
    "width": 100.0,
    "height": 60.0,
    "nx": 200,
    "ny": 120
  },
  "fluid": {
    "density": 1.225,
    "viscosity": 1.81e-5
  },
  "boundary_conditions": {
    "inlet_velocity": 5.0,
    "inlet_direction": 0.0,
    "turbulence_intensity": 0.05
  },
  "solver": {
    "max_iterations": 500,
    "turbulence_model": "sst"
  },
  "obstacles": [
    {
      "type": "building",
      "x_min": 20, "x_max": 40,
      "y_min": 25, "y_max": 45,
      "name": "Rakennus A"
    },
    {
      "type": "tree",
      "x_center": 50, "y_center": 35,
      "radius": 5, "porosity": 0.5,
      "name": "Puu 1"
    }
  ]
}
```

### Estetyypit

| Tyyppi | Parametrit | Kuvaus |
|--------|------------|--------|
| `building` | x_min, x_max, y_min, y_max | Kiinteä este (no-slip) |
| `tree` | x_center, y_center, radius, porosity | Huokoinen este |

## Turbulenssimallit

| Malli | Asetus | Tarkkuus | Nopeus | Käyttö |
|-------|--------|----------|--------|--------|
| Vakio ν_t | `"constant"` | ⭐ | ⭐⭐⭐⭐⭐ | Nopeat arviot |
| k-ε | `"k-epsilon"` | ⭐⭐⭐ | ⭐⭐⭐ | Teollisuusstandardi |
| k-ω SST | `"sst"` | ⭐⭐⭐⭐ | ⭐⭐⭐ | Paras tarkkuus |

## Tulosten analysointi

### Tuulisuusvyöhykkeet (Lawson)

| Vyöhyke | Nopeus | Soveltuvuus |
|---------|--------|-------------|
| Rauhallinen | < 2 m/s | Istuskelu, ulkoruokailu |
| Miellyttävä | 2-4 m/s | Kävely, oleskelu |
| Tuulinen | 4-6 m/s | Läpikulku |
| Epämukava | > 6 m/s | Ei pitkäaikaiseen oleskeluun |

### Painekerroin

```
Cp = p / (½ρU²)
```

- Cp > 0: Ylipaine (tuulenpuoli)
- Cp < 0: Alipaine (suojanpuoli)
- Cp ≈ 1: Staginaatiopiste

## Esimerkit

### Puusuojan vaikutus

```bash
python main.py --geometry examples/building_with_tree_shelter.json
```

### U-muotoinen sisäpiha

```bash
python main.py --geometry examples/u_shaped_courtyard.json --plot pressure
```

## Teoria

Ratkaisija perustuu:
- **Navier-Stokes -yhtälöihin** (stationaarinen)
- **SIMPLE-algoritmiin** (Semi-Implicit Method for Pressure-Linked Equations)
- **RANS-turbulenssimalleihin** (Reynolds-Averaged Navier-Stokes)

Tarkempi teoria: `docs/theory.md`

---

## 🔧 Tuotantoskriptit

### Automatisointi

| Skripti | Kuvaus | Käyttö |
|---------|--------|--------|
| `process_simulation_queue.py` | Pääprosessori joka käsittelee jonon | `python3 process_simulation_queue.py --max-tasks 1` |
| `osm_fetch.py` | Luo geometrian osoitteesta | `python3 osm_fetch.py --address "Osoite" --output file.json` |
| `approval_server.py` | QA-hyväksyntäpalvelin | Systemd-palvelu (port 8082) |
| `serve_results.py` | Tulospalvelin | Systemd-palvelu (port 8080) |
| `send_qa_notification.py` | Lähettää QA-emailin | Kutsutaan automaattisesti |
| `send_customer_email.py` | Lähettää asiakasemailin | Kutsutaan automaattisesti |

### Simulaatiojonon prosessointi

```bash
# Dry-run (ei muuta mitään)
python3 process_simulation_queue.py --dry-run

# Prosessoi max 1 tehtävä
python3 process_simulation_queue.py --max-tasks 1

# Prosessoi kaikki pending-tehtävät
python3 process_simulation_queue.py
```

### Geometrian luonti osoitteesta

```bash
# Luo geometria OpenStreetMap-datasta
python3 osm_fetch.py --address "Mannerheimintie 1, Helsinki" --output OSMgeometry/test.json

# Käytä suoraan simulaatiossa
./run_cfd.sh --geometry OSMgeometry/test.json --output results/test --resolution 1.0
```

### Systemd-palvelut

```bash
# Tarkista statukset
sudo systemctl status cfd-results-server
sudo systemctl status approval-server
sudo systemctl status cloudflared

# Käynnistä uudelleen
sudo systemctl restart cfd-results-server

# Seuraa lokeja
sudo journalctl -u approval-server -f
```

### Cron-lokit

```bash
# Email fetch
tail -f /home/eetu/apps/email_manager/logs/email_fetch.log

# Simulation queue processor
tail -f automation/logs/queue_processor.log
```

---

## 📂 Tuotantohakemistot

| Hakemisto | Tarkoitus |
|-----------|-----------|
| `/srv/simulations/<uuid>/` | Asiakaskohtaiset tulokset (julkiset linkit) |
| `results/` | Väliaikaiset tulokset (ennen kopiointia) |
| `OSMgeometry/` | Geometriatiedostot osoitteista |
| `automation/logs/` | Cron-lokit |
| `systemd/` | Systemd service -tiedostot |

---

## 🌐 Tuotanto-URLit

- **Tulokset:** https://microclimateanalysis.com/\<uuid\>/
- **QA-hyväksyntä:** https://microclimateanalysis.com/approve/\<uuid\>/\<token\>
- **QA-hylkäys:** https://microclimateanalysis.com/reject/\<uuid\>/\<token\>
- **Status:** https://microclimateanalysis.com/status/\<uuid\>

---

## 📚 Dokumentaatio

| Dokumentti | Kuvaus |
|------------|--------|
| `/home/eetu/apps/MIKROILMASTO_SYSTEM.md` | **Täydellinen järjestelmädokumentaatio** |
| `README.md` (tämä) | CFD-solverin käyttöohje |
| `docs/theory.md` | Matemaattinen teoria |
| `docs/turbulence_models.md` | Turbulenssimallien vertailu |
| `automation/README.md` | Cron-automatisointi |
| `systemd/README.md` | Systemd-palveluiden asennus |

---

## Lisenssi

MIT License

## Tekijät

Kehitetty rakennusfysiikan tutkimuskäyttöön.
**Tuotantojärjestelmä:** Loopshore (2026)
