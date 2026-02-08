#!/bin/bash
#
# CFD Microclimate - Käynnistysskripti
# Asettaa rinnakkaistuksen kaikille CPU-ytimille
#

# Värikoodit
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Skriptin sijainti
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

#
# Funktio: Siivoa vanhat CFD-prosessit
#
cleanup_old_processes() {
    echo -e "${YELLOW}Tarkistetaan vanhat main.py prosessit...${NC}"

    # Etsi main.py prosessit jotka ajetaan tästä kansiosta
    local pids=$(ps aux | grep "[p]ython.*main.py" | grep "$SCRIPT_DIR" | awk '{print $2}')

    if [ -z "$pids" ]; then
        echo -e "${GREEN}✓ Ei vanhoja prosesseja${NC}"
        return 0
    fi

    # Näytä löydetyt prosessit
    echo -e "${YELLOW}Löydettiin vanhoja prosesseja:${NC}"
    ps aux | grep "[p]ython.*main.py" | grep "$SCRIPT_DIR" | while read line; do
        echo "  $line"
    done

    # Tapa prosessit
    for pid in $pids; do
        echo -e "${YELLOW}Tapetaan prosessi $pid...${NC}"
        kill $pid 2>/dev/null
    done

    # Odota 3 sekuntia
    sleep 3

    # Tarkista jäikö jotain henkiin, pakkolopeta ne
    local remaining=$(ps aux | grep "[p]ython.*main.py" | grep "$SCRIPT_DIR" | awk '{print $2}')
    if [ ! -z "$remaining" ]; then
        echo -e "${RED}Pakkolopetetaan jumissa olevat prosessit...${NC}"
        for pid in $remaining; do
            kill -9 $pid 2>/dev/null
        done
        sleep 1
    fi

    echo -e "${GREEN}✓ Prosessit siivottu${NC}"
}

echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  CFD Mikroilmastosimulointi${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"

# Siivoa vanhat prosessit ennen uuden käynnistystä
cleanup_old_processes
echo ""

# Tarkista että virtuaaliympäristö on olemassa
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠ Virtuaaliympäristö puuttuu!${NC}"
    echo "Luodaan .venv..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    echo -e "${GREEN}✓ Virtuaaliympäristö luotu${NC}"
fi

# Laske CPU-ytimet
CPU_CORES=$(nproc)
echo -e "${GREEN}✓ CPU-ytimiä käytettävissä: ${CPU_CORES}${NC}"

# Aseta rinnakkaistus-asetukset
export NUMBA_NUM_THREADS=$CPU_CORES
export OMP_NUM_THREADS=$CPU_CORES
export MKL_NUM_THREADS=$CPU_CORES
export OPENBLAS_NUM_THREADS=$CPU_CORES

# Numban optimoinnit (workqueue = toimii ilman lisäkirjastoja)
# Ei aseteta NUMBA_THREADING_LAYER -> Numba valitsee parhaan saatavilla olevan
export NUMBA_WARNINGS=0  # Hiljennä varoitukset (valinnainen)
export NUMBA_CACHE_DIR="$SCRIPT_DIR/.numba_cache"  # Nopea uudelleenkäynnistys

echo -e "${GREEN}✓ Rinnakkaistus asetettu: ${CPU_CORES} säiettä${NC}"
echo -e "${BLUE}───────────────────────────────────────────────────${NC}"

# Aja Python-skripti
echo -e "${BLUE}Käynnistetään simulaatio...${NC}\n"

.venv/bin/python3 main.py "$@"

EXIT_CODE=$?

# Tulosta lopputulos
echo ""
echo -e "${BLUE}───────────────────────────────────────────────────${NC}"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Simulaatio valmis!${NC}"
else
    echo -e "${YELLOW}⚠ Simulaatio päättyi virheeseen (koodi: $EXIT_CODE)${NC}"
fi
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"

exit $EXIT_CODE
