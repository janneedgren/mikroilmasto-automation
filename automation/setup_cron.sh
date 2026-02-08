#!/bin/bash
# Asenna cron-job joka prosessoi simulaatiojonon tunnin välein

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
QUEUE_PROCESSOR="$PROJECT_DIR/process_simulation_queue.py"
LOG_DIR="$PROJECT_DIR/automation/logs"

# Luo log-hakemisto
mkdir -p "$LOG_DIR"

# Cron-komento
CRON_CMD="0 * * * * cd $PROJECT_DIR && /usr/bin/python3 $QUEUE_PROCESSOR --max-tasks 1 >> $LOG_DIR/queue_processor.log 2>&1"

echo "Setting up cron job for simulation queue processing..."
echo ""
echo "Cron schedule: Every hour (0 * * * *)"
echo "Script: $QUEUE_PROCESSOR"
echo "Max tasks per run: 1"
echo "Logs: $LOG_DIR/queue_processor.log"
echo ""

# Tarkista onko cron-job jo olemassa
if crontab -l 2>/dev/null | grep -q "process_simulation_queue.py"; then
    echo "⚠️  Cron job already exists. Updating..."
    # Poista vanha
    crontab -l 2>/dev/null | grep -v "process_simulation_queue.py" | crontab -
fi

# Lisää uusi cron-job
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -

echo "✅ Cron job installed successfully!"
echo ""
echo "Verify with:"
echo "  crontab -l"
echo ""
echo "View logs:"
echo "  tail -f $LOG_DIR/queue_processor.log"
echo ""
echo "Manual run (test):"
echo "  cd $PROJECT_DIR && python3 $QUEUE_PROCESSOR --dry-run"
echo ""
echo "Remove cron job:"
echo "  crontab -e  (then delete the line with 'process_simulation_queue.py')"
