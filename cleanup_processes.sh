#!/bin/bash
#
# Siivoa kaikki CFD main.py prosessit
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Värikoodit
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}  CFD Prosessien siivous${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
echo ""

# Etsi main.py prosessit
pids=$(ps aux | grep "[p]ython.*main.py" | grep "$SCRIPT_DIR" | awk '{print $2}')

if [ -z "$pids" ]; then
    echo -e "${GREEN}✓ Ei prosesseja siivottavana${NC}"
    exit 0
fi

# Näytä prosessit
echo -e "${YELLOW}Löydetyt main.py prosessit:${NC}"
echo ""
ps aux | grep "[p]ython.*main.py" | grep "$SCRIPT_DIR" | nl
echo ""

# Kysy vahvistus
read -p "Tapatko nämä prosessit? (y/N): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Peruutettu.${NC}"
    exit 0
fi

# Tapa prosessit (SIGTERM)
echo -e "${YELLOW}Lähetetään SIGTERM...${NC}"
for pid in $pids; do
    echo "  Tapetaan PID $pid"
    kill $pid 2>/dev/null
done

# Odota
echo "Odotetaan 5 sekuntia..."
sleep 5

# Tarkista onko vielä jotain
remaining=$(ps aux | grep "[p]ython.*main.py" | grep "$SCRIPT_DIR" | awk '{print $2}')

if [ ! -z "$remaining" ]; then
    echo -e "${RED}Jotkin prosessit eivät kuolleet, pakkolopetus (SIGKILL)...${NC}"
    for pid in $remaining; do
        echo "  Pakkolopetus PID $pid"
        kill -9 $pid 2>/dev/null
    done
    sleep 1
fi

# Tarkista lopputulos
final=$(ps aux | grep "[p]ython.*main.py" | grep "$SCRIPT_DIR" | awk '{print $2}')

if [ -z "$final" ]; then
    echo ""
    echo -e "${GREEN}✓ Kaikki prosessit siivottu!${NC}"
else
    echo ""
    echo -e "${RED}✗ Joitain prosesseja jäi jäljelle:${NC}"
    ps aux | grep "[p]ython.*main.py" | grep "$SCRIPT_DIR"
    exit 1
fi

echo -e "${YELLOW}═══════════════════════════════════════════════════${NC}"
