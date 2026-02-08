#!/bin/bash
# Mikroilmastoanalyysi - Täydellinen automatisointi
# Asentaa cron-jobit sekä email-hakulle että simulaatioiden käynnistykselle

set -e

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Mikroilmastoanalyysi - Täysi automatisointi             ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Värit
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Hakemistot
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
EMAIL_MANAGER_DIR="/home/eetu/apps/email_manager"
LOG_DIR_CFD="$PROJECT_DIR/automation/logs"
LOG_DIR_EMAIL="$EMAIL_MANAGER_DIR/logs"

# Luo log-hakemistot
mkdir -p "$LOG_DIR_CFD"
mkdir -p "$LOG_DIR_EMAIL"

echo -e "${BLUE}Konfiguraatio:${NC}"
echo "  CFD Project:     $PROJECT_DIR"
echo "  Email Manager:   $EMAIL_MANAGER_DIR"
echo "  Logs (CFD):      $LOG_DIR_CFD"
echo "  Logs (Email):    $LOG_DIR_EMAIL"
echo ""

# Cron-komennot (käytä venv-Pythonia jotta OSM-kirjastot löytyvät)
CRON_EMAIL="0 * * * * cd $EMAIL_MANAGER_DIR && $EMAIL_MANAGER_DIR/.venv/bin/python3 fetch_mikroilmasto_emails.py >> $LOG_DIR_EMAIL/email_fetch.log 2>&1"
CRON_QUEUE="5 * * * * cd $PROJECT_DIR && $PROJECT_DIR/.venv/bin/python3 process_simulation_queue.py --max-tasks 1 >> $LOG_DIR_CFD/queue_processor.log 2>&1"

echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}Cron-jobit:${NC}"
echo ""
echo -e "${GREEN}1. Email-haku (joka tasatunti)${NC}"
echo "   Aikataulu: 0 * * * * (00:00, 01:00, 02:00...)"
echo "   Skripti:   fetch_mikroilmasto_emails.py"
echo "   Loki:      $LOG_DIR_EMAIL/email_fetch.log"
echo ""
echo -e "${GREEN}2. Simulaatiojonon prosessointi (5min tasatunnin jälkeen)${NC}"
echo "   Aikataulu: 5 * * * * (00:05, 01:05, 02:05...)"
echo "   Skripti:   process_simulation_queue.py"
echo "   Max tasks: 1 per ajo"
echo "   Loki:      $LOG_DIR_CFD/queue_processor.log"
echo ""
echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"

# Tarkista että tarvittavat skriptit löytyvät
echo ""
echo -e "${BLUE}Tarkistetaan skriptit...${NC}"

if [ ! -f "$EMAIL_MANAGER_DIR/fetch_mikroilmasto_emails.py" ]; then
    echo -e "${YELLOW}⚠️  fetch_mikroilmasto_emails.py ei löydy!${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} fetch_mikroilmasto_emails.py"

if [ ! -f "$PROJECT_DIR/process_simulation_queue.py" ]; then
    echo -e "${YELLOW}⚠️  process_simulation_queue.py ei löydy!${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} process_simulation_queue.py"

# Poista vanhat cron-jobit (jos olemassa)
echo ""
echo -e "${BLUE}Poistetaan vanhat cron-jobit (jos olemassa)...${NC}"

if crontab -l 2>/dev/null | grep -q "fetch_mikroilmasto_emails.py"; then
    echo -e "  ${YELLOW}Poistetaan vanha email-fetch cron${NC}"
    crontab -l 2>/dev/null | grep -v "fetch_mikroilmasto_emails.py" | crontab -
fi

if crontab -l 2>/dev/null | grep -q "process_simulation_queue.py"; then
    echo -e "  ${YELLOW}Poistetaan vanha queue-processor cron${NC}"
    crontab -l 2>/dev/null | grep -v "process_simulation_queue.py" | crontab -
fi

# Lisää uudet cron-jobit
echo ""
echo -e "${BLUE}Asennetaan uudet cron-jobit...${NC}"

(crontab -l 2>/dev/null; echo "# Mikroilmastoanalyysi - Email fetch (every hour at :00)") | crontab -
(crontab -l 2>/dev/null; echo "$CRON_EMAIL") | crontab -
echo -e "  ${GREEN}✓${NC} Email-fetch cron asennettu (joka tasatunti)"

(crontab -l 2>/dev/null; echo "") | crontab -
(crontab -l 2>/dev/null; echo "# Mikroilmastoanalyysi - Queue processor (every hour at :05)") | crontab -
(crontab -l 2>/dev/null; echo "$CRON_QUEUE") | crontab -
echo -e "  ${GREEN}✓${NC} Queue-processor cron asennettu (5min tasatunnin jälkeen)"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅ Automatisointi asennettu onnistuneesti!             ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

echo "═══════════════════════════════════════════════════════════"
echo "YHTEENVETO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📧 Email-haku:"
echo "   • Ajastettu: Joka tasatunti (00:00, 01:00...)"
echo "   • Hakee uudet tilaukset Gmailista"
echo "   • Luo pending-tehtävät task queue:hun"
echo ""
echo "🚀 Simulaatioiden käynnistys:"
echo "   • Ajastettu: 5min tasatunnin jälkeen (00:05, 01:05...)"
echo "   • Prosessoi 1 tehtävän kerralla"
echo "   • Käynnistyy automaattisesti ilman ihmisen väliintuloa"
echo "   • Maksimaalinen viive: 1h 5min (jos email tulee heti tasatunnin jälkeen)"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "SEURAAVAT VAIHEET"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "1. Tarkista cron-jobit:"
echo "   crontab -l"
echo ""
echo "2. Testaa email-fetch heti:"
echo "   cd $EMAIL_MANAGER_DIR"
echo "   python3 fetch_mikroilmasto_emails.py"
echo ""
echo "3. Testaa queue-processor heti:"
echo "   cd $PROJECT_DIR"
echo "   python3 process_simulation_queue.py --max-tasks 1"
echo ""
echo "4. Seuraa lokeja reaaliajassa:"
echo "   # Email-fetch"
echo "   tail -f $LOG_DIR_EMAIL/email_fetch.log"
echo ""
echo "   # Queue-processor"
echo "   tail -f $LOG_DIR_CFD/queue_processor.log"
echo ""
echo "5. Odota seuraavaa cron-ajoa:"
echo "   • Email-haku: Seuraava tasatunti (esim. 10:00, 11:00...)"
echo "   • Simulaatio: 5min tasatunnin jälkeen (esim. 10:05, 11:05...)"
echo ""
echo "   TÄYSIN AUTOMAATTINEN - ei vaadi ihmisen väliintuloa!"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "HYÖDYLLISIÄ KOMENTOJA"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "# Katso kaikki cron-jobit"
echo "crontab -l"
echo ""
echo "# Muokkaa cron-jobeja"
echo "crontab -e"
echo ""
echo "# Tarkista cron-daemon"
echo "systemctl status cron"
echo ""
echo "# Katso viimeisimmät cron-ajot (Ubuntu/Debian)"
echo "grep CRON /var/log/syslog | tail -20"
echo ""
echo "# Katso task queue"
echo "cat $EMAIL_MANAGER_DIR/data/mikroilmasto_tasks.json | jq"
echo ""
echo "═══════════════════════════════════════════════════════════"
