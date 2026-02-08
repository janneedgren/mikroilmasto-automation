#!/bin/bash
# Testaa automatisoinnin komponentit ennen asennusta

set -e

# Värit
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Mikroilmastoanalyysi - Automatisoinnin testaus          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
EMAIL_MANAGER_DIR="/home/eetu/apps/email_manager"

ERRORS=0

# Funktio: tarkista tiedosto
check_file() {
    if [ -f "$1" ]; then
        echo -e "  ${GREEN}✓${NC} $2"
        return 0
    else
        echo -e "  ${RED}✗${NC} $2 - PUUTTUU!"
        ((ERRORS++))
        return 1
    fi
}

# Funktio: tarkista hakemisto
check_dir() {
    if [ -d "$1" ]; then
        echo -e "  ${GREEN}✓${NC} $2"
        return 0
    else
        echo -e "  ${YELLOW}⚠${NC}  $2 - Luodaan..."
        mkdir -p "$1"
        return 0
    fi
}

echo -e "${BLUE}1. Tarkistetaan skriptit...${NC}"
check_file "$EMAIL_MANAGER_DIR/fetch_mikroilmasto_emails.py" "Email fetcher"
check_file "$PROJECT_DIR/process_simulation_queue.py" "Queue processor"
check_file "$PROJECT_DIR/run_cfd.sh" "CFD runner"
echo ""

echo -e "${BLUE}2. Tarkistetaan hakemistot...${NC}"
check_dir "$EMAIL_MANAGER_DIR/data" "Email data dir"
check_dir "$EMAIL_MANAGER_DIR/logs" "Email logs dir"
check_dir "$PROJECT_DIR/automation/logs" "CFD logs dir"
check_dir "/srv/simulations" "Simulations root"
echo ""

echo -e "${BLUE}3. Tarkistetaan email credentials...${NC}"
if [ -f "$EMAIL_MANAGER_DIR/config/email_credentials.json" ]; then
    echo -e "  ${GREEN}✓${NC} Gmail credentials löytyvät"
else
    echo -e "  ${RED}✗${NC} Gmail credentials PUUTTUU!"
    echo "     → Kopioi email_credentials.json config/-kansioon"
    ((ERRORS++))
fi
echo ""

echo -e "${BLUE}4. Testataan email fetcher (dry-run)...${NC}"
cd "$EMAIL_MANAGER_DIR"
if python3 fetch_mikroilmasto_emails.py --dry-run > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Email fetcher toimii"
else
    echo -e "  ${RED}✗${NC} Email fetcher VIRHE!"
    echo "     → Aja: cd $EMAIL_MANAGER_DIR && python3 fetch_mikroilmasto_emails.py --dry-run"
    ((ERRORS++))
fi
echo ""

echo -e "${BLUE}5. Testataan queue processor (dry-run)...${NC}"
cd "$PROJECT_DIR"
if python3 process_simulation_queue.py --dry-run > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Queue processor toimii"
else
    echo -e "  ${RED}✗${NC} Queue processor VIRHE!"
    echo "     → Aja: cd $PROJECT_DIR && python3 process_simulation_queue.py --dry-run"
    ((ERRORS++))
fi
echo ""

echo -e "${BLUE}6. Tarkistetaan cron-daemon...${NC}"
if systemctl is-active --quiet cron; then
    echo -e "  ${GREEN}✓${NC} Cron daemon käynnissä"
else
    echo -e "  ${YELLOW}⚠${NC}  Cron daemon EI käynnissä!"
    echo "     → Käynnistä: sudo systemctl start cron"
fi
echo ""

echo -e "${BLUE}7. Tarkistetaan Python-riippuvuudet...${NC}"
cd "$PROJECT_DIR"
if [ -d ".venv" ]; then
    echo -e "  ${GREEN}✓${NC} Virtual environment löytyy"
else
    echo -e "  ${YELLOW}⚠${NC}  Virtual environment puuttuu"
    echo "     → Luo: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi
echo ""

echo "═══════════════════════════════════════════════════════════"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ KAIKKI TESTIT LÄPI!${NC}"
    echo ""
    echo "Voit nyt asentaa automatisoinnin:"
    echo "  bash $SCRIPT_DIR/setup_full_automation.sh"
else
    echo -e "${RED}❌ LÖYDETTIIN $ERRORS VIRHETTÄ!${NC}"
    echo ""
    echo "Korjaa virheet ennen automatisoinnin asennusta."
fi
echo "═══════════════════════════════════════════════════════════"
