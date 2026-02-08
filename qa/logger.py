#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MikroilmastoCFD - Laadunvarmistusloki (QA Logger)

Kerää ja tallentaa simuloinnin tiedot validointia varten:
- Järjestelmätiedot (CPU, GPU, RAM, OS)
- Simulointikomento ja parametrit
- Kasvillisuusalueiden turbulenssitilastot (TI, k, ω, k/U²)
- Konvergenssin tiedot
- Suoritusaika

Käyttö:
    from qa_logger import QALogger
    
    qa = QALogger(output_dir="results/")
    qa.start_simulation(command=sys.argv, config=config)
    
    # ... simulointi ...
    
    qa.log_convergence(iterations=1500, residual=1.2e-5, converged=True)
    qa.extract_vegetation_statistics(solver, config)
    qa.extract_building_surface_statistics(solver, config)
    qa.end_simulation()
    qa.save()

Tuomas Alinikula, Loopshore Oy, 2026
"""

import json
import csv
import os
import sys
import platform
import time
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import numpy as np


class QALogger:
    """
    Laadunvarmistusloki CFD-simuloinneille.
    
    Tallentaa simuloinnin tiedot JSON- ja CSV-muodossa validointia varten.
    """
    
    # Lokin versio - päivitetään jos rakenne muuttuu
    VERSION = "1.0.0"
    
    def __init__(self, output_dir: str = ".", log_name: str = "qa_validation_log"):
        """
        Args:
            output_dir: Hakemisto johon lokit tallennetaan
            log_name: Lokitiedoston perusnimi (ilman päätettä)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_name = log_name
        self.json_path = self.output_dir / f"{log_name}.json"
        self.csv_path = self.output_dir / f"{log_name}.csv"
        
        # Nykyisen simuloinnin tiedot
        self.current_entry = {}
        self.start_time = None
        
        # Lataa olemassa oleva loki jos löytyy
        self.log_entries = self._load_existing_log()
        
        # Kerää järjestelmätiedot kerran
        self.system_info = self._collect_system_info()
    
    def _load_existing_log(self) -> List[Dict]:
        """Lataa olemassa oleva JSON-loki."""
        if self.json_path.exists():
            try:
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('entries', [])
            except (json.JSONDecodeError, KeyError):
                print(f"  QA: Varoitus - olemassa olevaa lokia ei voitu lukea, luodaan uusi")
                return []
        return []
    
    def _collect_system_info(self) -> Dict:
        """Kerää järjestelmätiedot."""
        info = {
            'os': f"{platform.system()} {platform.release()}",
            'os_version': platform.version(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'python_version': platform.python_version(),
            'cpu_count': os.cpu_count(),
        }
        
        # CPU-tiedot (yksityiskohtaisemmat)
        try:
            if platform.system() == 'Windows':
                import subprocess
                result = subprocess.run(['wmic', 'cpu', 'get', 'name'], 
                                       capture_output=True, text=True, timeout=5)
                cpu_name = result.stdout.strip().split('\n')[-1].strip()
                if cpu_name:
                    info['cpu_name'] = cpu_name
            elif platform.system() == 'Linux':
                with open('/proc/cpuinfo', 'r') as f:
                    for line in f:
                        if 'model name' in line:
                            info['cpu_name'] = line.split(':')[1].strip()
                            break
            elif platform.system() == 'Darwin':
                import subprocess
                result = subprocess.run(['sysctl', '-n', 'machdep.cpu.brand_string'],
                                       capture_output=True, text=True, timeout=5)
                info['cpu_name'] = result.stdout.strip()
        except Exception:
            pass
        
        # RAM
        try:
            import psutil
            mem = psutil.virtual_memory()
            info['ram_total_gb'] = round(mem.total / (1024**3), 1)
            info['ram_available_gb'] = round(mem.available / (1024**3), 1)
        except ImportError:
            # Yritä ilman psutil
            try:
                if platform.system() == 'Linux':
                    with open('/proc/meminfo', 'r') as f:
                        for line in f:
                            if 'MemTotal' in line:
                                mem_kb = int(line.split()[1])
                                info['ram_total_gb'] = round(mem_kb / (1024**2), 1)
                                break
            except Exception:
                pass
        
        # GPU (NVIDIA)
        try:
            import subprocess
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                gpu_info = result.stdout.strip().split(',')
                info['gpu_name'] = gpu_info[0].strip()
                info['gpu_memory'] = gpu_info[1].strip() if len(gpu_info) > 1 else None
        except Exception:
            info['gpu_name'] = None
        
        # NumPy/Numba versiot
        try:
            info['numpy_version'] = np.__version__
        except:
            pass
        
        try:
            import numba
            info['numba_version'] = numba.__version__
        except ImportError:
            pass
        
        return info
    
    def start_simulation(self, 
                        command: List[str] = None,
                        geometry_path: str = None,
                        config: Any = None,
                        description: str = None):
        """
        Aloittaa uuden simuloinnin lokin.
        
        Args:
            command: Komentorivikomento (sys.argv)
            geometry_path: Geometriatiedoston polku
            config: GeometryConfig-olio
            description: Vapaamuotoinen kuvaus
        """
        self.start_time = time.time()
        timestamp = datetime.datetime.now()
        
        # Luo uniikki ID
        sim_id = timestamp.strftime("%Y-%m-%d_%H-%M-%S")
        if geometry_path:
            sim_id += f"_{Path(geometry_path).stem}"
        
        self.current_entry = {
            'simulation_id': sim_id,
            'timestamp': timestamp.isoformat(),
            'qa_logger_version': self.VERSION,
            'command': ' '.join(command) if command else None,
            'geometry_file': str(geometry_path) if geometry_path else None,
            'description': description,
            'system': self.system_info.copy(),
        }
        
        # Lisää config-tiedot jos annettu
        if config:
            self._extract_config(config)
    
    def _extract_config(self, config):
        """Poimii oleelliset tiedot configista."""
        try:
            self.current_entry['input_parameters'] = {
                'domain_width': config.domain.width,
                'domain_height': config.domain.height,
                'grid_nx': config.domain.nx,
                'grid_ny': config.domain.ny,
                'grid_dx': config.domain.width / config.domain.nx,
                'grid_dy': config.domain.height / config.domain.ny,
                'turbulence_model': config.solver.turbulence_model,
                'max_iterations': config.solver.max_iterations,
                'inlet_velocity': config.boundary_conditions.inlet_velocity,
                'wind_direction': getattr(config.boundary_conditions, 'wind_direction', None),
                'turbulence_intensity': getattr(config.boundary_conditions, 'turbulence_intensity', 0.05),
            }
            
            # Kasvillisuusalueiden määrä
            n_tree_zones = 0
            n_veg_zones = 0
            n_buildings = 0
            for obs in config.obstacles:
                obs_type = type(obs).__name__
                if 'TreeZone' in obs_type:
                    n_tree_zones += 1
                elif 'Vegetation' in obs_type:
                    n_veg_zones += 1
                elif 'Building' in obs_type or 'Polygon' in obs_type or 'Rotated' in obs_type:
                    n_buildings += 1
            
            self.current_entry['input_parameters']['n_buildings'] = n_buildings
            self.current_entry['input_parameters']['n_tree_zones'] = n_tree_zones
            self.current_entry['input_parameters']['n_vegetation_zones'] = n_veg_zones
            
            # Projektin nimi
            if config.name:
                self.current_entry['project_name'] = config.name
                
        except Exception as e:
            print(f"  QA: Varoitus - config-tietojen poiminta epäonnistui: {e}")
    
    def log_convergence(self, iterations: int, residual: float, converged: bool):
        """
        Tallentaa konvergenssitiedot.
        
        Args:
            iterations: Suoritettujen iteraatioiden määrä
            residual: Lopullinen residuaali
            converged: Konvergoituiko laskenta
        """
        self.current_entry['convergence'] = {
            'iterations': iterations,
            'residual_final': float(residual),
            'converged': converged
        }
    
    def _get_obs_attr(self, obs, attr: str, default=None):
        """
        Hakee attribuutin arvon sekä dict- että dataclass-olioista.
        
        Combined-laskennassa solver.obstacles voi sisältää dict-olioita,
        kun taas normaalissa laskennassa ne ovat dataclass-olioita.
        """
        if isinstance(obs, dict):
            return obs.get(attr, default)
        else:
            return getattr(obs, attr, default)
    
    def _is_vegetation_zone(self, obs) -> bool:
        """
        Tarkista onko este kasvillisuusalue (toimii dict ja dataclass).
        """
        # Dict-olio
        if isinstance(obs, dict):
            obs_type = obs.get('type', '')
            return (obs.get('LAI') is not None or 
                    obs.get('vegetation_type') is not None or
                    'tree_zone' in obs_type or 
                    'vegetation' in obs_type)
        # Dataclass-olio
        else:
            return (hasattr(obs, 'LAI') or 
                    hasattr(obs, 'vegetation_type') or
                    'TreeZone' in type(obs).__name__ or
                    'Vegetation' in type(obs).__name__)
    
    def extract_vegetation_statistics(self, solver, config, 
                                      inlet_velocity: float = None) -> Dict:
        """
        Poimii turbulenssitilastot kasvillisuusalueilta.
        
        Laskee jokaiselle kasvillisuusalueelle:
        - TI (turbulenssi-intensiteetti) = √(2k/3) / U
        - k (turbulenssienergian tiheys)
        - ω (spesifinen dissipaationopeus)
        - k/U² (normalisoitu turbulenssienergia)
        - ν_t (turbulentti viskositeetti)
        
        Args:
            solver: CFDSolver-olio (ratkaistu)
            config: GeometryConfig-olio
            inlet_velocity: Sisääntulon nopeus (käytetään normalisointiin)
            
        Returns:
            Dict kasvillisuusalueiden tilastoista
        """
        if solver.turb_model is None:
            return {}
        
        # Hae turbulenssikentät
        fields = solver.turb_model.get_turbulence_fields()
        k = fields.get('k')
        omega = fields.get('omega')
        nu_t = fields.get('nu_t')
        
        if k is None or omega is None:
            return {}
        
        # Nopeuskenttä
        U_mag = np.sqrt(solver.u**2 + solver.v**2)
        U_ref = inlet_velocity or solver.bc.inlet_velocity
        
        # TI-kenttä: TI = √(2k/3) / U
        with np.errstate(divide='ignore', invalid='ignore'):
            TI = np.sqrt(2.0 * k / 3.0) / np.maximum(U_mag, 0.1)
            TI = np.nan_to_num(TI, nan=0.0, posinf=0.0)
        
        # k/U² normalisoitu turbulenssienergia
        with np.errstate(divide='ignore', invalid='ignore'):
            k_over_U2 = k / np.maximum(U_ref**2, 0.1)
            k_over_U2 = np.nan_to_num(k_over_U2, nan=0.0, posinf=0.0)
        
        vegetation_stats = []
        
        # Käy läpi kaikki kasvillisuusalueet
        for obs in solver.obstacles:
            # Tarkista onko kasvillisuusalue (toimii dict ja dataclass)
            if not self._is_vegetation_zone(obs):
                continue
            
            # Luo maski kasvillisuusalueelle
            mask = self._create_zone_mask(obs, solver)
            
            if mask is None or not np.any(mask):
                continue
            
            # Ohita solid-solut
            valid_mask = mask & ~solver.solid_mask
            
            if not np.any(valid_mask):
                continue
            
            # Poimi arvot
            k_zone = k[valid_mask]
            omega_zone = omega[valid_mask]
            TI_zone = TI[valid_mask] * 100.0  # Prosentteina
            k_over_U2_zone = k_over_U2[valid_mask]
            nu_t_zone = nu_t[valid_mask] if nu_t is not None else None
            U_zone = U_mag[valid_mask]
            
            # Pinnan konvektiivinen lämmönsiirtokerroin h_c [W/m²K]
            # EN ISO 6946:2017: h_c = 4 + 4v (v ≤ 5 m/s), h_c = 7.1v^0.78 (v > 5 m/s)
            # Kuvaa tuulen aiheuttamaa konvektiivista lämmönsiirtoa pinnalla
            h_c_zone = np.where(U_zone <= 5.0, 4.0 + 4.0 * U_zone, 7.1 * np.power(U_zone, 0.78))
            
            # Hae attribuutit (toimii dict ja dataclass)
            zone_type_raw = self._get_obs_attr(obs, 'vegetation_type', 'tree_zone')
            # Varmista että zone_type on string
            if isinstance(zone_type_raw, dict):
                zone_type = zone_type_raw.get('type', zone_type_raw.get('name', str(zone_type_raw)))
            else:
                zone_type = str(zone_type_raw) if zone_type_raw else 'tree_zone'
            
            # Ohita ei-kasvillisuustyypit (vesi, tiet, kosteikko yms.)
            _exclude_types = ['road', 'lake', 'water', 'pond', 'river', 'reservoir',
                              'parking', 'asphalt', 'sand', 'bare', 'wetland', 'reed']
            if any(ex in zone_type.lower() for ex in _exclude_types):
                continue
            
            stats = {
                'zone_id': self._get_obs_attr(obs, 'name') or f"zone_{len(vegetation_stats)+1}",
                'zone_type': zone_type,
                'LAI': self._get_obs_attr(obs, 'LAI'),
                'LAI_2D': self._get_obs_attr(obs, 'LAI_2D'),
                'height': self._get_obs_attr(obs, 'height'),
                'porosity': self._get_obs_attr(obs, 'porosity'),
                'n_cells': int(np.sum(valid_mask)),
                
                # TI [%]
                'TI_mean': float(np.mean(TI_zone)),
                'TI_std': float(np.std(TI_zone)),
                'TI_min': float(np.min(TI_zone)),
                'TI_max': float(np.max(TI_zone)),
                'TI_p5': float(np.percentile(TI_zone, 5)),
                'TI_p95': float(np.percentile(TI_zone, 95)),
                
                # k [m²/s²]
                'k_mean': float(np.mean(k_zone)),
                'k_std': float(np.std(k_zone)),
                'k_min': float(np.min(k_zone)),
                'k_max': float(np.max(k_zone)),
                
                # omega [1/s]
                'omega_mean': float(np.mean(omega_zone)),
                'omega_std': float(np.std(omega_zone)),
                'omega_min': float(np.min(omega_zone)),
                'omega_max': float(np.max(omega_zone)),
                
                # k/U² [-]
                'k_over_U2_mean': float(np.mean(k_over_U2_zone)),
                'k_over_U2_std': float(np.std(k_over_U2_zone)),
                
                # U [m/s] kasvillisuusalueella
                'U_mean': float(np.mean(U_zone)),
                'U_std': float(np.std(U_zone)),
                
                # h_c [W/m²K] pinnan konvektiivinen lämmönsiirtokerroin (EN ISO 6946)
                'h_c_mean': float(np.mean(h_c_zone)),
                'h_c_std': float(np.std(h_c_zone)),
                'h_c_min': float(np.min(h_c_zone)),
                'h_c_max': float(np.max(h_c_zone)),
                'h_c_p5': float(np.percentile(h_c_zone, 5)),
                'h_c_p95': float(np.percentile(h_c_zone, 95)),
            }
            
            # nu_t jos saatavilla
            if nu_t_zone is not None:
                stats['nu_t_mean'] = float(np.mean(nu_t_zone))
                stats['nu_t_max'] = float(np.max(nu_t_zone))
            
            vegetation_stats.append(stats)
        
        self.current_entry['vegetation_validation'] = vegetation_stats
        return {'vegetation_zones': vegetation_stats}
    
    def _create_zone_mask(self, obs, solver) -> Optional[np.ndarray]:
        """Luo maski kasvillisuusalueelle (toimii dict ja dataclass)."""
        ny, nx = solver.domain.ny, solver.domain.nx
        dx, dy = solver.domain.dx, solver.domain.dy
        
        mask = np.zeros((ny, nx), dtype=bool)
        
        # Hae vertices (toimii dict ja dataclass)
        vertices = self._get_obs_attr(obs, 'vertices') or self._get_obs_attr(obs, 'vertices_list')
        
        if vertices is not None:
            try:
                from matplotlib.path import Path as MplPath
                
                # Luo polygon path
                poly_path = MplPath(vertices)
                
                # Luo pisteet kaikille soluille
                y_coords = np.arange(ny) * dy
                x_coords = np.arange(nx) * dx
                xx, yy = np.meshgrid(x_coords, y_coords)
                points = np.column_stack((xx.ravel(), yy.ravel()))
                
                # Tarkista mitkä pisteet ovat polygonin sisällä
                inside = poly_path.contains_points(points)
                mask = inside.reshape((ny, nx))
                
            except Exception as e:
                print(f"  QA: Varoitus - polygonimaskin luonti epäonnistui: {e}")
                return None
        
        else:
            # Ympyrä (puu)
            x_center = self._get_obs_attr(obs, 'x_center')
            y_center = self._get_obs_attr(obs, 'y_center')
            radius = self._get_obs_attr(obs, 'radius')
            
            if x_center is not None and radius is not None:
                y_coords = np.arange(ny) * dy
                x_coords = np.arange(nx) * dx
                xx, yy = np.meshgrid(x_coords, y_coords)
                dist = np.sqrt((xx - x_center)**2 + (yy - y_center)**2)
                mask = dist <= radius
        
        return mask
    
    def extract_building_surface_statistics(self, solver, config) -> Dict:
        """
        Laskee rakennusten pinnan konvektiiviset lämmönsiirtokertoimet 
        u_tau-menetelmällä (Jayatilleke thermal wall function).
        
        Laskentaketju:
        1. u_tau = C_mu^0.25 * sqrt(k) seinänvierussolusta
        2. y+ = u_tau * y_wall / nu
        3. T+ Jayatilleken (1969) termisestä seinäfunktiosta
        4. h_c = rho * c_p * u_tau / T+
        
        Lähteet:
        - Jayatilleke (1969): The influence of Prandtl number...
        - Blocken et al. (2009): CFD building surface heat transfer
        - EN ISO 6946:2017: Building components thermal resistance
        
        Args:
            solver: CFDSolver-olio (ratkaistu)
            config: GeometryConfig-olio
            
        Returns:
            Dict rakennusten pintatilastoista
        """
        if solver.turb_model is None:
            return {}
        
        fields = solver.turb_model.get_turbulence_fields()
        k = fields.get('k')
        if k is None:
            return {}
        
        # Ilman ominaisuudet (T ~ 10°C, tyypillinen ulkoilma)
        rho = 1.225       # kg/m³
        c_p = 1005.0      # J/(kg·K)
        nu = 1.5e-5       # m²/s (kinemaattinen viskositeetti)
        Pr = 0.71         # Prandtl-luku (ilma)
        Pr_t = 0.85       # Turbulentti Prandtl
        kappa = 0.41      # von Kármán
        B_log = 5.2       # Logaritmisen seinälain vakio
        C_mu = 0.09       # k-omega/k-epsilon vakio
        C_mu_025 = C_mu ** 0.25  # ≈ 0.5477
        
        # Jayatilleken P-funktio: P(Pr) 
        P_jay = 9.24 * ((Pr / Pr_t) ** 0.75 - 1.0) * (
            1.0 + 0.28 * np.exp(-0.007 * Pr / Pr_t))
        
        ny, nx = solver.solid_mask.shape
        dx = solver.domain.dx
        dy = getattr(solver.domain, 'dy', dx)
        
        # Naapurisuunnat: (di, dj, seinäetäisyys)
        neighbors = [(0, 1, dx / 2.0), (0, -1, dx / 2.0),
                     (1, 0, dy / 2.0), (-1, 0, dy / 2.0)]
        
        building_stats = []
        
        for obs in solver.obstacles:
            # Ohita kasvillisuus
            if self._is_vegetation_zone(obs):
                continue
            
            # Rakennusmaski
            bld_mask = self._create_zone_mask(obs, solver)
            if bld_mask is None or not np.any(bld_mask):
                continue
            
            # Vain solid-solut tästä rakennuksesta
            bld_solid = bld_mask & solver.solid_mask
            if not np.any(bld_solid):
                continue
            
            bld_indices = np.argwhere(bld_solid)
            
            # Kerää seinänvierussolut ja laske h_c
            h_c_values = []
            u_tau_values = []
            
            seen = set()  # Estä saman solun moninkertainen laskenta
            
            for (iy, ix) in bld_indices:
                for di, dj, y_wall in neighbors:
                    ni, nj = iy + di, ix + dj
                    if (0 <= ni < ny and 0 <= nj < nx 
                            and not solver.solid_mask[ni, nj]
                            and (ni, nj) not in seen):
                        seen.add((ni, nj))
                        
                        k_val = max(float(k[ni, nj]), 1e-10)
                        u_tau = C_mu_025 * np.sqrt(k_val)
                        y_plus = u_tau * y_wall / nu
                        
                        # T+ Jayatilleken terminen seinäfunktio
                        if y_plus < 11.6:
                            T_plus = Pr * max(y_plus, 0.1)
                        else:
                            T_plus = (Pr_t * (np.log(max(y_plus, 1.0)) / kappa + B_log)
                                      + P_jay)
                        
                        T_plus = max(T_plus, 0.1)
                        h_c = rho * c_p * u_tau / T_plus
                        
                        h_c_values.append(h_c)
                        u_tau_values.append(u_tau)
            
            if not h_c_values:
                continue
            
            h_c_arr = np.array(h_c_values)
            u_tau_arr = np.array(u_tau_values)
            
            stats = {
                'building_id': (self._get_obs_attr(obs, 'name') 
                                or self._get_obs_attr(obs, 'id')
                                or f"bld_{len(building_stats) + 1}"),
                'is_target': bool(self._get_obs_attr(obs, 'is_target', False)),
                'height': self._get_obs_attr(obs, 'height'),
                'n_wall_cells': len(h_c_values),
                
                # h_c [W/m²K]
                'h_c_mean': float(np.mean(h_c_arr)),
                'h_c_std': float(np.std(h_c_arr)),
                'h_c_min': float(np.min(h_c_arr)),
                'h_c_max': float(np.max(h_c_arr)),
                'h_c_p5': float(np.percentile(h_c_arr, 5)),
                'h_c_p95': float(np.percentile(h_c_arr, 95)),
                
                # u_tau [m/s]
                'u_tau_mean': float(np.mean(u_tau_arr)),
                'u_tau_max': float(np.max(u_tau_arr)),
            }
            
            building_stats.append(stats)
        
        self.current_entry['building_surface'] = building_stats
        return {'building_surface': building_stats}
    
    def log_custom_metric(self, name: str, value: Any, category: str = "custom"):
        """
        Tallentaa mukautetun metriikan.
        
        Args:
            name: Metriikan nimi
            value: Arvo (JSON-serialisoitava)
            category: Kategoria (oletus "custom")
        """
        if category not in self.current_entry:
            self.current_entry[category] = {}
        self.current_entry[category][name] = value
    
    def end_simulation(self):
        """Lopettaa simuloinnin ja laskee kokonaisajan jos ei jo asetettu."""
        # Älä ylikirjoita jos duration_seconds on jo asetettu ulkoisesti
        if 'duration_seconds' not in self.current_entry or self.current_entry.get('duration_seconds', 0) == 0:
            if self.start_time:
                elapsed = time.time() - self.start_time
                self.current_entry['duration_seconds'] = round(elapsed, 2)
                self.current_entry['duration_formatted'] = self._format_duration(elapsed)
        else:
            # Muotoile aika jos duration_seconds on jo asetettu
            elapsed = self.current_entry.get('duration_seconds', 0)
            self.current_entry['duration_formatted'] = self._format_duration(elapsed)
    
    def _format_duration(self, seconds: float) -> str:
        """Muotoilee ajan luettavaan muotoon."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h {mins}m"
    
    def save(self):
        """Tallentaa lokin JSON- ja CSV-muodossa."""
        if not self.current_entry:
            return
        
        # Lisää nykyinen merkintä listaan
        self.log_entries.append(self.current_entry)
        
        # Tallenna JSON
        self._save_json()
        
        # Tallenna/päivitä CSV
        self._save_csv()
        
        print(f"  QA: Loki tallennettu: {self.json_path}")
    
    def _save_json(self):
        """Tallentaa JSON-lokin."""
        data = {
            'qa_logger_version': self.VERSION,
            'created': datetime.datetime.now().isoformat(),
            'total_simulations': len(self.log_entries),
            'entries': self.log_entries
        }
        
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _save_csv(self):
        """Tallentaa/päivittää CSV-lokin kasvillisuustilastoista."""
        # Kerää kaikki kasvillisuustilastot kaikista simuloinneista
        rows = []
        
        for entry in self.log_entries:
            sim_id = entry.get('simulation_id', '')
            timestamp = entry.get('timestamp', '')
            duration = entry.get('duration_seconds', '')
            project = entry.get('project_name', '')
            
            # Input parameters
            params = entry.get('input_parameters', {})
            wind_dir = params.get('wind_direction', '')
            inlet_vel = params.get('inlet_velocity', '')
            
            # Kasvillisuustilastot
            veg_stats = entry.get('vegetation_validation', [])
            
            for zone in veg_stats:
                # Varmista että zone_type on string (voi olla dict vanhassa datassa)
                zone_type = zone.get('zone_type', '')
                if isinstance(zone_type, dict):
                    zone_type = zone_type.get('type', zone_type.get('name', str(zone_type)))
                zone_type = str(zone_type) if zone_type else ''
                
                row = {
                    'simulation_id': sim_id,
                    'timestamp': timestamp,
                    'project': project,
                    'wind_direction': wind_dir,
                    'inlet_velocity': inlet_vel,
                    'duration_s': duration,
                    
                    'zone_id': zone.get('zone_id', ''),
                    'zone_type': zone_type,
                    'LAI': zone.get('LAI', ''),
                    'LAI_2D': zone.get('LAI_2D', ''),
                    'height': zone.get('height', ''),
                    'porosity': zone.get('porosity', ''),
                    'n_cells': zone.get('n_cells', ''),
                    
                    'TI_mean': zone.get('TI_mean', ''),
                    'TI_p5': zone.get('TI_p5', ''),
                    'TI_p95': zone.get('TI_p95', ''),
                    
                    'k_mean': zone.get('k_mean', ''),
                    'k_min': zone.get('k_min', ''),
                    'k_max': zone.get('k_max', ''),
                    
                    'omega_mean': zone.get('omega_mean', ''),
                    'omega_min': zone.get('omega_min', ''),
                    'omega_max': zone.get('omega_max', ''),
                    
                    'k_over_U2_mean': zone.get('k_over_U2_mean', ''),
                    
                    'U_mean': zone.get('U_mean', ''),
                    'nu_t_mean': zone.get('nu_t_mean', ''),
                }
                rows.append(row)
        
        if not rows:
            return
        
        # Kirjoita CSV
        try:
            fieldnames = list(rows[0].keys())
            
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        except Exception as e:
            print(f"  [QA] Varoitus: CSV-tallennus epäonnistui: {e}")
    
    def get_summary(self) -> Dict:
        """
        Palauttaa yhteenvedon kaikista simuloinneista.
        
        Hyödyllinen validointitaulukon generointiin.
        """
        if not self.log_entries:
            return {}
        
        # Kerää kasvillisuustilastot tyypeittäin
        stats_by_type = {}
        
        for entry in self.log_entries:
            for zone in entry.get('vegetation_validation', []):
                zone_type = zone.get('zone_type', 'unknown')
                
                # Varmista että zone_type on string (voi olla dict vanhassa datassa)
                if isinstance(zone_type, dict):
                    zone_type = zone_type.get('type', zone_type.get('name', str(zone_type)))
                zone_type = str(zone_type) if zone_type else 'unknown'
                
                if zone_type not in stats_by_type:
                    stats_by_type[zone_type] = {
                        'TI_values': [],
                        'k_values': [],
                        'omega_values': [],
                        'k_over_U2_values': [],
                        'count': 0
                    }
                
                stats_by_type[zone_type]['TI_values'].append(zone.get('TI_mean', 0))
                stats_by_type[zone_type]['k_values'].append(zone.get('k_mean', 0))
                stats_by_type[zone_type]['omega_values'].append(zone.get('omega_mean', 0))
                stats_by_type[zone_type]['k_over_U2_values'].append(zone.get('k_over_U2_mean', 0))
                stats_by_type[zone_type]['count'] += 1
        
        # Laske yhteenvetotilastot
        summary = {}
        
        for zone_type, data in stats_by_type.items():
            if data['count'] == 0:
                continue
            
            summary[zone_type] = {
                'n_simulations': data['count'],
                'TI_range': f"{min(data['TI_values']):.1f}-{max(data['TI_values']):.1f}%",
                'TI_mean': f"{np.mean(data['TI_values']):.1f}%",
                'omega_range': f"{min(data['omega_values']):.2f}-{max(data['omega_values']):.2f} 1/s",
                'k_over_U2_range': f"{min(data['k_over_U2_values']):.3f}-{max(data['k_over_U2_values']):.3f}",
            }
        
        return {
            'total_simulations': len(self.log_entries),
            'vegetation_summary': summary
        }
    
    def generate_validation_table(self) -> str:
        """
        Generoi validointitaulukko Markdown-muodossa.
        
        Voidaan käyttää wdr_esite.py -skriptin taulukon päivittämiseen.
        """
        summary = self.get_summary()
        
        if not summary:
            return "Ei simulointidataa."
        
        lines = [
            "| Suure | Simuloitu | Kirjallisuus | Lähde |",
            "|-------|-----------|--------------|-------|"
        ]
        
        veg = summary.get('vegetation_summary', {})
        
        # Metsä
        if 'tree_zone' in veg or 'forest' in veg or 'mixed_forest' in veg:
            forest_data = veg.get('tree_zone') or veg.get('forest') or veg.get('mixed_forest', {})
            lines.append(f"| TI metsässä | {forest_data.get('TI_range', 'N/A')} | 10-20% | Finnigan (2000) |")
            lines.append(f"| ω metsässä | {forest_data.get('omega_range', 'N/A')} | 0.3-3.0 1/s | Sogachev (2006) |")
            lines.append(f"| k/U² metsässä | {forest_data.get('k_over_U2_range', 'N/A')} | 0.02-0.08 | Katul et al. (2004) |")
        
        # Pensaikko
        if 'shrub' in veg or 'scrub' in veg:
            shrub_data = veg.get('shrub') or veg.get('scrub', {})
            lines.append(f"| TI pensaikossa | {shrub_data.get('TI_range', 'N/A')} | 15-30% | Shaw & Schumann |")
        
        return '\n'.join(lines)


# ============================================================================
# INTEGRAATIO MAIN.PY:HÖN
# ============================================================================

def integrate_qa_logging(main_function):
    """
    Dekoraattori joka lisää QA-lokituksen simulointifunktioon.
    
    Käyttö:
        @integrate_qa_logging
        def run_simulation(args, config, ...):
            ...
    """
    def wrapper(*args, **kwargs):
        # Luo QA logger
        output_dir = kwargs.get('output_dir', '.')
        qa = QALogger(output_dir=str(output_dir))
        
        # Aloita lokitus
        qa.start_simulation(
            command=sys.argv,
            geometry_path=kwargs.get('geometry_path'),
            config=kwargs.get('config')
        )
        
        # Suorita alkuperäinen funktio
        try:
            result = main_function(*args, **kwargs)
            
            # Poimi tulokset jos solver palautetaan
            if isinstance(result, tuple) and len(result) >= 3:
                solver, converged, elapsed = result[:3]
                
                # Lokita konvergenssi
                if hasattr(solver, 'iteration'):
                    residual = getattr(solver, 'last_residual', 0.0)
                    qa.log_convergence(solver.iteration, residual, converged)
                
                # Poimi kasvillisuustilastot
                config = kwargs.get('config')
                if config:
                    qa.extract_vegetation_statistics(solver, config)
                    qa.extract_building_surface_statistics(solver, config)
            
            return result
            
        finally:
            qa.end_simulation()
            qa.save()
    
    return wrapper


# ============================================================================
# TESTAUS
# ============================================================================

if __name__ == '__main__':
    # Testaa QA loggeria
    print("QA Logger - Testi")
    print("="*50)
    
    qa = QALogger(output_dir="/tmp/qa_test")
    
    # Simuloi simulointia
    qa.start_simulation(
        command=['python', 'main.py', '--geometry', 'test.json'],
        geometry_path='test.json',
        description='Testisimulointi'
    )
    
    # Lisää testitietoja
    qa.current_entry['input_parameters'] = {
        'domain_width': 200,
        'domain_height': 200,
        'grid_nx': 200,
        'grid_ny': 200,
        'turbulence_model': 'sst',
        'inlet_velocity': 5.0
    }
    
    # Simuloi kasvillisuustilastoja
    qa.current_entry['vegetation_validation'] = [
        {
            'zone_id': 'F1',
            'zone_type': 'tree_zone',
            'LAI': 5.0,
            'LAI_2D': 1.75,
            'height': 15.0,
            'TI_mean': 15.2,
            'TI_p5': 12.0,
            'TI_p95': 18.5,
            'k_mean': 0.85,
            'omega_mean': 1.2,
            'k_over_U2_mean': 0.034,
            'U_mean': 3.2,
            'n_cells': 1500
        }
    ]
    
    qa.log_convergence(iterations=1500, residual=1.2e-5, converged=True)
    qa.end_simulation()
    qa.save()
    
    print("\nJärjestelmätiedot:")
    for key, value in qa.system_info.items():
        print(f"  {key}: {value}")
    
    print("\nYhteenveto:")
    summary = qa.get_summary()
    print(json.dumps(summary, indent=2))
    
    print("\nValidointitaulukko:")
    print(qa.generate_validation_table())
    
    print(f"\nTiedostot tallennettu: {qa.json_path}, {qa.csv_path}")
