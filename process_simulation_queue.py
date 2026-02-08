#!/usr/bin/env python3
"""
Mikroilmastoanalyysi - Simulaatiojonon prosessoija

Lukee mikroilmasto_tasks.json tiedostosta pending-tehtävät,
käynnistää CFD-simulaatiot ja kopioi tulokset asiakkaan UUID-hakemistoon.

Käyttö:
    python3 process_simulation_queue.py
    python3 process_simulation_queue.py --dry-run
    python3 process_simulation_queue.py --max-tasks 1
"""

import json
import re
import subprocess
import shutil
import logging
import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import secrets

# Konfiguraatio
SCRIPT_DIR = Path(__file__).parent
TASKS_FILE = Path("/home/eetu/apps/email_manager/data/mikroilmasto_tasks.json")
RESULTS_BASE = SCRIPT_DIR / "results"
SIMULATIONS_ROOT = Path("/srv/simulations")
RUN_CFD_SCRIPT = SCRIPT_DIR / "run_cfd.sh"
OSM_GEOMETRY_DIR = SCRIPT_DIR / "OSMgeometry"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SimulationQueueProcessor:
    """Käsittelee simulaatiojonon tehtävät."""

    def __init__(self, dry_run: bool = False, max_tasks: Optional[int] = None):
        self.dry_run = dry_run
        self.max_tasks = max_tasks

    def load_tasks(self) -> Dict[str, Any]:
        """Lataa tehtävälista JSON-tiedostosta."""
        if not TASKS_FILE.exists():
            logger.warning(f"Tasks file not found: {TASKS_FILE}")
            return {"tasks": [], "last_updated": None}

        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_tasks(self, data: Dict[str, Any]):
        """Tallenna päivitetty tehtävälista."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would save {len(data['tasks'])} tasks")
            return

        data["last_updated"] = datetime.now().isoformat()

        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(data['tasks'])} tasks to {TASKS_FILE}")

    def get_pending_tasks(self, tasks: List[Dict]) -> List[Dict]:
        """Palauta pending-tilassa olevat tehtävät."""
        return [t for t in tasks if t.get("status") == "pending"]

    def update_task_status(
        self,
        task: Dict,
        status: str,
        error_message: Optional[str] = None
    ):
        """Päivitä tehtävän status."""
        task["status"] = status
        task["status_updated_at"] = datetime.now().isoformat()

        if error_message:
            task["error_message"] = error_message

        # Käytä UUID:ta jos saatavilla, muuten osoitetta
        task_id = task.get('simulation_uuid', task.get('osoite', 'unknown'))[:8]
        logger.info(f"Task {task_id}... → {status}")

    def sanitize_filename(self, text: str) -> str:
        """Muuta osoite turvalliseksi tiedostonimeksi."""
        # Poista erikoismerkit ja korvaa välilyönnit
        safe = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in text)
        safe = safe.replace(' ', '_')
        # Rajoita pituus
        return safe[:100].strip('_')

    def clean_address_for_osm(self, address: str) -> str:
        """
        Puhdista osoite OpenStreetMap-hakua varten poistamalla huoneistotunnukset.

        Esimerkit:
            "Hämeenkatu 13 A5 Tampere" → "Hämeenkatu 13 Tampere"
            "Mannerheimintie 5 B 12 Helsinki" → "Mannerheimintie 5 Helsinki"
            "Kalevankatu 3 1A Turku" → "Kalevankatu 3 Turku"
            "Keskuskatu 10 Oulu" → "Keskuskatu 10 Oulu" (ei muutosta)

        Args:
            address: Alkuperäinen osoite (voi sisältää huoneistotunnuksen)

        Returns:
            Puhdistettu osoite ilman huoneistotunnusta
        """
        # Poista huoneistotunnukset eri muodoissa:
        # 1. Kirjain + välilyönti + numerot: " A 5", " B 12"
        cleaned = re.sub(r'\s+[A-ZÅÄÖ]\s+\d+\b', ' ', address)

        # 2. Kirjain + numerot ilman välilyöntiä: " A5", " B12"
        cleaned = re.sub(r'\s+[A-ZÅÄÖ]\d+\b', ' ', cleaned)

        # 3. Porrastunnukset: " 1A", " 2B" jne.
        cleaned = re.sub(r'\s+\d+[A-ZÅÄÖ]\b', ' ', cleaned)

        # 4. Yksittäinen kirjain: " A", " B" (vain jos ei ole osa kaupungin nimeä)
        # Tehdään tämä viimeisenä, jotta edellä olevat patternit käsittävät ensin
        cleaned = re.sub(r'\s+[A-ZÅÄÖ]\b(?=\s)', ' ', cleaned)

        # Poista ylimääräiset välilyönnit
        cleaned = ' '.join(cleaned.split())

        if cleaned != address:
            logger.info(f"Cleaned address for OSM:")
            logger.info(f"  Original: {address}")
            logger.info(f"  Cleaned:  {cleaned}")

        return cleaned

    def create_geometry_from_address(self, address: str, output_dir: Path) -> Optional[Path]:
        """
        Luo geometria-JSON tiedosto osoitteesta käyttäen osm_fetch.py:tä.

        Returns:
            Path to generated JSON file or None if failed
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would create geometry for: {address}")
            return output_dir / "generated_geometry.json"

        try:
            # Tarkista onko osm_fetch.py olemassa
            osm_fetch = SCRIPT_DIR / "osm_fetch.py"
            if not osm_fetch.exists():
                logger.error(f"osm_fetch.py not found at {osm_fetch}")
                return None

            # Luo output-hakemisto
            output_dir.mkdir(parents=True, exist_ok=True)

            # Sanitoi osoite tiedostonimeksi
            safe_name = self.sanitize_filename(address)
            geometry_file = output_dir / f"{safe_name}.json"

            # Suorita osm_fetch.py
            logger.info(f"Creating geometry from address: {address}")
            cmd = [
                sys.executable,
                str(osm_fetch),
                "--address", address,
                "--output", str(geometry_file)
            ]

            result = subprocess.run(
                cmd,
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                timeout=300  # 5min timeout
            )

            if result.returncode != 0:
                logger.error(f"osm_fetch failed: {result.stderr}")
                return None

            if not geometry_file.exists():
                logger.error(f"Geometry file not created: {geometry_file}")
                return None

            logger.info(f"✓ Geometry created: {geometry_file}")
            return geometry_file

        except subprocess.TimeoutExpired:
            logger.error(f"osm_fetch timed out for address: {address}")
            return None
        except Exception as e:
            logger.error(f"Failed to create geometry: {e}")
            return None

    def run_cfd_simulation(
        self,
        geometry_file: Path,
        output_dir: Path,
        resolution: float = 1.0
    ) -> bool:
        """
        Suorita CFD-simulaatio käyttäen run_cfd.sh skriptiä.

        Args:
            geometry_file: Polku geometria-JSON tiedostoon
            output_dir: Tuloskohteiden hakemisto
            resolution: Hilaresolaatio (metriä)

        Returns:
            True jos simulaatio onnistui
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would run simulation: {geometry_file}")
            return True

        try:
            output_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"Running CFD simulation...")
            logger.info(f"  Geometry: {geometry_file}")
            logger.info(f"  Output: {output_dir}")
            logger.info(f"  Resolution: {resolution}m")

            # Rakenna komento
            cmd = [
                str(RUN_CFD_SCRIPT),
                "--geometry", str(geometry_file),
                "--output", str(output_dir),
                "--resolution", str(resolution),
                "--wdr"  # Ota WDR-analyysi mukaan
            ]

            # Suorita simulaatio
            result = subprocess.run(
                cmd,
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                timeout=7200  # 2h timeout
            )

            if result.returncode != 0:
                logger.error(f"CFD simulation failed!")
                logger.error(f"STDOUT: {result.stdout[-500:]}")  # Last 500 chars
                logger.error(f"STDERR: {result.stderr[-500:]}")
                return False

            logger.info("✓ CFD simulation completed successfully")
            return True

        except subprocess.TimeoutExpired:
            logger.error("CFD simulation timed out (2h limit)")
            return False
        except Exception as e:
            logger.error(f"Failed to run simulation: {e}")
            return False

    def copy_results_to_customer_directory(
        self,
        simulation_output: Path,
        customer_dir: Path
    ) -> bool:
        """
        Kopioi simulaation tulokset asiakkaan UUID-hakemistoon.

        Args:
            simulation_output: Simulaation tuloshakemisto
            customer_dir: Asiakkaan UUID-hakemisto (/srv/simulations/<uuid>/)

        Returns:
            True jos kopiointi onnistui
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would copy {simulation_output} → {customer_dir}")
            return True

        try:
            customer_dir.mkdir(parents=True, exist_ok=True)

            # Kopioi kaikki tiedostot ja kansiot
            if simulation_output.exists():
                logger.info(f"Copying results to customer directory...")

                # Käytä shutil.copytree rekursiiviseen kopiointiin
                for item in simulation_output.iterdir():
                    dest = customer_dir / item.name

                    if item.is_dir():
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(item, dest)
                    else:
                        shutil.copy2(item, dest)

                logger.info(f"✓ Results copied to: {customer_dir}")
                return True
            else:
                logger.error(f"Simulation output not found: {simulation_output}")
                return False

        except Exception as e:
            logger.error(f"Failed to copy results: {e}")
            return False

    def send_qa_notification(self, task: Dict) -> bool:
        """Lähetä QA-notifikaatio."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would send QA notification for task: {task['simulation_uuid'][:8]}")
            return True

        try:
            from send_qa_notification import send_qa_notification
            return send_qa_notification(task)
        except Exception as e:
            logger.error(f"Failed to send QA notification: {e}")
            return False

    def clean_caches(self, geometry_dir: Path, simulation_output: Path) -> None:
        """
        Siivoa edellisten ajojen jäänteet ennen uutta simulaatiota.

        Poistaa:
        1. osmnx Overpass API cache (./cache/) - estää vanhan geometrian käytön
        2. Edellisen ajon geometria samalle osoitteelle
        3. Edellisen ajon simulaatiotulokset samalle osoitteelle
        4. Numba ja Python __pycache__ -hakemistot (solvers, geometry)
        """
        if self.dry_run:
            logger.info("[DRY-RUN] Would clean caches")
            return

        # 1. osmnx Overpass API cache
        osmnx_cache = SCRIPT_DIR / "cache"
        if osmnx_cache.exists():
            shutil.rmtree(osmnx_cache)
            logger.info(f"Cleaned osmnx cache: {osmnx_cache}")

        # 2. Edellisen ajon geometria samalle osoitteelle
        if geometry_dir.exists():
            shutil.rmtree(geometry_dir)
            logger.info(f"Cleaned old geometry: {geometry_dir}")

        # 3. Edellisen ajon tulokset samalle osoitteelle
        if simulation_output.exists():
            shutil.rmtree(simulation_output)
            logger.info(f"Cleaned old simulation output: {simulation_output}")

        # 4. Python/Numba __pycache__ hakemistot (vain projektin omat)
        for cache_dir in SCRIPT_DIR.rglob("__pycache__"):
            if ".venv" not in str(cache_dir):
                shutil.rmtree(cache_dir)
        logger.info("Cleaned __pycache__ directories")

    def process_task(self, task: Dict) -> bool:
        """
        Prosessoi yksi tehtävä: luo geometria, suorita simulaatio, kopioi tulokset.

        Returns:
            True jos onnistui
        """
        # Luo UUID jos puuttuu (vanhat taskit)
        if "simulation_uuid" not in task:
            import uuid as uuid_lib
            task["simulation_uuid"] = str(uuid_lib.uuid4())
            logger.info(f"Created missing UUID for old task: {task['simulation_uuid']}")

        # Varmista että simulation_directory on asetettu
        if "simulation_directory" not in task or task["simulation_directory"] is None:
            task["simulation_directory"] = str(SIMULATIONS_ROOT / task["simulation_uuid"])
            logger.info(f"Set simulation_directory: {task['simulation_directory']}")

        # Varmista että results_url on asetettu
        if "results_url" not in task or task["results_url"] is None:
            task["results_url"] = f"https://microclimateanalysis.com/{task['simulation_uuid']}/"
            logger.info(f"Set results_url: {task['results_url']}")

        uuid = task["simulation_uuid"]
        address = task["osoite"]
        customer_name = task["nimi"]

        logger.info("="*60)
        logger.info(f"Processing task: {uuid}")
        logger.info(f"  Customer: {customer_name}")
        logger.info(f"  Address: {address}")
        logger.info("="*60)

        try:
            # Generoi QA approval token heti alussa (tarvitaan myös virhetilanteissa)
            if not self.dry_run:
                token = secrets.token_urlsafe(32)
                task["qa_approval_token"] = token
                task["qa_approval_expires_at"] = (datetime.now() + timedelta(days=7)).isoformat()

            # Tallenna aloitusaika
            task["simulation_started_at"] = datetime.now().isoformat()

            # 1. Luo hakemistot
            safe_name = self.sanitize_filename(address)
            geometry_dir = OSM_GEOMETRY_DIR / safe_name
            simulation_output = RESULTS_BASE / safe_name / "analysis"
            customer_dir = Path(task["simulation_directory"])

            # 1b. Siivoa edellisten ajojen jäänteet (estää tulosten sekoittumisen)
            self.clean_caches(geometry_dir, simulation_output)

            # 2. Puhdista osoite OSM-hakua varten (poista huoneistotunnukset)
            cleaned_address = self.clean_address_for_osm(address)

            # 3. Luo geometria osoitteesta
            geometry_file = self.create_geometry_from_address(cleaned_address, geometry_dir)
            if not geometry_file:
                raise Exception("Failed to create geometry")

            # 4. Suorita CFD-simulaatio
            success = self.run_cfd_simulation(
                geometry_file=geometry_file,
                output_dir=simulation_output,
                resolution=1.0  # 1m hilaresolaatio
            )

            if not success:
                raise Exception("CFD simulation failed")

            # 5. Kopioi tulokset asiakkaan hakemistoon
            success = self.copy_results_to_customer_directory(
                simulation_output=simulation_output,
                customer_dir=customer_dir
            )

            if not success:
                raise Exception("Failed to copy results")

            # 6. Tallenna simulaation tiedot
            task["simulation_completed_at"] = datetime.now().isoformat()

            # Laske kesto
            if "simulation_started_at" in task:
                start = datetime.fromisoformat(task["simulation_started_at"])
                end = datetime.fromisoformat(task["simulation_completed_at"])
                task["simulation_duration_seconds"] = int((end - start).total_seconds())

            # Tallenna parametrit
            task["simulation_parameters"] = {
                "resolution": 1.0,
                "wdr_enabled": True,
                "wind_directions": 8
            }

            logger.info("✓ Task completed successfully!")
            return True

        except Exception as e:
            logger.error(f"✗ Task failed: {e}")
            task["error_message"] = str(e)
            return False

    def run(self) -> Dict[str, int]:
        """Pääsilmukka: prosessoi pending-tehtävät."""
        stats = {
            "total_tasks": 0,
            "pending_tasks": 0,
            "processed": 0,
            "completed": 0,
            "failed": 0,
        }

        # Lataa tehtävät
        task_data = self.load_tasks()
        tasks = task_data.get("tasks", [])
        stats["total_tasks"] = len(tasks)

        # Hae pending-tehtävät
        pending_tasks = self.get_pending_tasks(tasks)
        stats["pending_tasks"] = len(pending_tasks)

        if not pending_tasks:
            logger.info("No pending tasks in queue")
            return stats

        logger.info(f"Found {len(pending_tasks)} pending tasks")

        # Rajoita prosessoitavien määrää
        if self.max_tasks:
            pending_tasks = pending_tasks[:self.max_tasks]
            logger.info(f"Processing max {self.max_tasks} tasks")

        # Prosessoi tehtävät
        for task in pending_tasks:
            stats["processed"] += 1

            # Päivitä status: processing
            self.update_task_status(task, "processing")
            self.save_tasks(task_data)

            # Suorita simulaatio
            success = self.process_task(task)

            # Päivitä lopputila
            if success:
                # Simulaatio onnistui → pending_approval
                self.update_task_status(task, "pending_approval")

                # Lähetä QA-notifikaatio
                qa_sent = self.send_qa_notification(task)
                if qa_sent:
                    task["qa_notification_sent_at"] = datetime.now().isoformat()
                    logger.info("✓ QA notification sent")
                else:
                    logger.warning("⚠ QA notification failed")

                stats["completed"] += 1
            else:
                # Simulaatio epäonnistui → failed
                self.update_task_status(task, "failed")

                # Lähetä QA-notifikaatio virheestä
                qa_sent = self.send_qa_notification(task)
                if qa_sent:
                    task["qa_notification_sent_at"] = datetime.now().isoformat()
                    logger.info("✓ QA error notification sent")

                stats["failed"] += 1

            # Tallenna välitilanteen status
            self.save_tasks(task_data)

        logger.info("Queue processing completed")
        return stats


def main():
    parser = argparse.ArgumentParser(
        description="Process mikroilmastoanalyysi simulation queue"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually run simulations or modify tasks"
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        help="Maximum number of tasks to process (default: unlimited)"
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("Running in DRY-RUN mode")

    processor = SimulationQueueProcessor(
        dry_run=args.dry_run,
        max_tasks=args.max_tasks
    )

    try:
        stats = processor.run()

        print("\n" + "="*60)
        print("SIMULATION QUEUE PROCESSING COMPLETE")
        print("="*60)
        print(f"Total tasks:     {stats['total_tasks']}")
        print(f"Pending tasks:   {stats['pending_tasks']}")
        print(f"Processed:       {stats['processed']}")
        print(f"Completed:       {stats['completed']}")
        print(f"Failed:          {stats['failed']}")
        print(f"\nTasks file: {TASKS_FILE}")

        if args.dry_run:
            print("\n[DRY-RUN] No changes were made")

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
