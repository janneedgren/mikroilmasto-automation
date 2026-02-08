"""
One-way Nested Grid CFD-simulointiin.

Mahdollistaa tarkan laskennan kiinnostavalla alueella käyttäen
karkeaa hilaa reunaehtojen määrittämiseen.

Toimintaperiaate:
1. Ratkaistaan karkea hila koko domainille
2. Interpoloidaan reunaehdot tiheälle alihilalle karkeasta ratkaisusta
3. Ratkaistaan tiheä hila tarkalla resoluutiolla
4. Yhdistetään tulokset

Käyttö:
    nested = NestedGridSolver(coarse_solver, fine_bounds, refinement=4)
    nested.solve()
    nested.plot_results(output_dir)
"""

import numpy as np
from scipy.interpolate import RegularGridInterpolator
from typing import Tuple, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class NestedRegion:
    """Määrittelee tiheän hilan alueen."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    refinement: int = 4  # Kuinka monta kertaa tiheämpi hila
    
    @property
    def width(self) -> float:
        return self.x_max - self.x_min
    
    @property
    def height(self) -> float:
        return self.y_max - self.y_min


class NestedGridSolver:
    """
    One-way nested grid CFD-ratkaisija.
    
    Käyttää karkeaa ratkaisua reunaehtojen interpolointiin
    tiheälle alihilalle.
    """
    
    def __init__(self, 
                 coarse_solver,
                 fine_region: NestedRegion,
                 fine_solver_class=None):
        """
        Args:
            coarse_solver: Ratkaistu karkea CFDSolver
            fine_region: Tiheän hilan alue ja asetukset
            fine_solver_class: CFDSolver-luokka (oletus: sama kuin coarse)
        """
        self.coarse = coarse_solver
        self.region = fine_region
        self.fine = None
        self.fine_solver_class = fine_solver_class
        
        # Validoi että alue on domainin sisällä
        if (fine_region.x_min < 0 or 
            fine_region.x_max > coarse_solver.domain.width or
            fine_region.y_min < 0 or 
            fine_region.y_max > coarse_solver.domain.height):
            raise ValueError("Fine region must be inside coarse domain")
        
        # Laske tiheän hilan parametrit
        self.fine_dx = coarse_solver.domain.dx / fine_region.refinement
        self.fine_dy = coarse_solver.domain.dy / fine_region.refinement
        self.fine_nx = int(fine_region.width / self.fine_dx)
        self.fine_ny = int(fine_region.height / self.fine_dy)
        
        print(f"Nested Grid konfiguraatio:")
        print(f"  Karkea hila: {coarse_solver.domain.nx} × {coarse_solver.domain.ny}, "
              f"dx={coarse_solver.domain.dx:.3f} m")
        print(f"  Tiheä hila:  {self.fine_nx} × {self.fine_ny}, "
              f"dx={self.fine_dx:.3f} m")
        print(f"  Tihennyskerroin: {fine_region.refinement}×")
        print(f"  Tiheä alue: x=[{fine_region.x_min:.0f}, {fine_region.x_max:.0f}], "
              f"y=[{fine_region.y_min:.0f}, {fine_region.y_max:.0f}]")
    
    def _create_interpolators(self) -> Dict[str, RegularGridInterpolator]:
        """Luo interpolaattorit karkeasta ratkaisusta."""
        # Karkean hilan koordinaatit
        x_coarse = np.linspace(0, self.coarse.domain.width, self.coarse.domain.nx)
        y_coarse = np.linspace(0, self.coarse.domain.height, self.coarse.domain.ny)
        
        interpolators = {}
        
        # Nopeudet
        interpolators['u'] = RegularGridInterpolator(
            (y_coarse, x_coarse), self.coarse.u, 
            method='linear', bounds_error=False, fill_value=None
        )
        interpolators['v'] = RegularGridInterpolator(
            (y_coarse, x_coarse), self.coarse.v,
            method='linear', bounds_error=False, fill_value=None
        )
        
        # Paine
        interpolators['p'] = RegularGridInterpolator(
            (y_coarse, x_coarse), self.coarse.p,
            method='linear', bounds_error=False, fill_value=None
        )
        
        # Turbulenssisuureet jos saatavilla
        if self.coarse.turb_model is not None:
            fields = self.coarse.turb_model.get_turbulence_fields()
            
            if 'k' in fields and fields['k'] is not None:
                k_coarse = fields['k'].copy()  # Kopioi jotta ei muuteta alkuperäistä
                # Debug: näytä karkean hilan k-arvot
                k_nonzero = k_coarse[~self.coarse.solid_mask]
                print(f"  Karkea k (ei-kiinteät): min={k_nonzero.min():.2e}, max={k_nonzero.max():.2e}, mean={k_nonzero.mean():.2e}")
                
                # TÄRKEÄ: Korvaa kiinteiden solujen k freestream-arvolla
                # Suodata pois hyvin pienet arvot (k_min = 1e-10) ennen mediaanin laskentaa
                k_reasonable = k_nonzero[k_nonzero > 1e-6]  # Vain k > 1e-6
                if len(k_reasonable) > 0:
                    k_freestream = np.median(k_reasonable)
                else:
                    k_freestream = 0.01  # Fallback
                
                k_coarse[self.coarse.solid_mask] = k_freestream
                print(f"  Solid solut korvattu k={k_freestream:.2e} interpolointia varten")
                
                interpolators['k'] = RegularGridInterpolator(
                    (y_coarse, x_coarse), k_coarse,
                    method='linear', bounds_error=False, fill_value=None
                )
            
            if 'omega' in fields and fields['omega'] is not None:
                omega_coarse = fields['omega'].copy()  # Kopioi jotta ei muuteta alkuperäistä
                omega_nonzero = omega_coarse[~self.coarse.solid_mask]
                print(f"  Karkea omega (ei-kiinteät): min={omega_nonzero.min():.2e}, max={omega_nonzero.max():.2e}, mean={omega_nonzero.mean():.2e}")
                
                # TÄRKEÄ: Korvaa kiinteiden solujen omega freestream-arvolla
                # Suodata pois hyvin pienet arvot (omega_min = 1e-10) ennen mediaanin laskentaa
                omega_reasonable = omega_nonzero[omega_nonzero > 1.0]  # Vain ω > 1
                if len(omega_reasonable) > 0:
                    omega_freestream = np.median(omega_reasonable)
                else:
                    omega_freestream = 100.0  # Fallback
                
                omega_coarse[self.coarse.solid_mask] = omega_freestream
                print(f"  Solid solut korvattu omega={omega_freestream:.1f} interpolointia varten")
                
                interpolators['omega'] = RegularGridInterpolator(
                    (y_coarse, x_coarse), omega_coarse,
                    method='linear', bounds_error=False, fill_value=None
                )
            
            if 'epsilon' in fields and fields['epsilon'] is not None:
                eps_coarse = fields['epsilon'].copy()
                eps_nonzero = eps_coarse[~self.coarse.solid_mask]
                eps_freestream = np.median(eps_nonzero)
                eps_coarse[self.coarse.solid_mask] = eps_freestream
                
                interpolators['epsilon'] = RegularGridInterpolator(
                    (y_coarse, x_coarse), eps_coarse,
                    method='linear', bounds_error=False, fill_value=None
                )
        
        return interpolators
    
    def _interpolate_boundary_conditions(self, interpolators: Dict) -> Dict[str, np.ndarray]:
        """
        Interpoloi reunaehdot karkeasta ratkaisusta tiheälle hilalle.
        
        Returns:
            Dict jossa 'west', 'east', 'south', 'north' reunojen arvot
        """
        # Tiheän hilan reunakoordinaatit
        x_fine = np.linspace(self.region.x_min, self.region.x_max, self.fine_nx)
        y_fine = np.linspace(self.region.y_min, self.region.y_max, self.fine_ny)
        
        bc = {}
        
        # Länsi (west) reuna: x = x_min
        west_points = np.array([[y, self.region.x_min] for y in y_fine])
        bc['west'] = {
            'u': interpolators['u'](west_points),
            'v': interpolators['v'](west_points),
            'p': interpolators['p'](west_points)
        }
        
        # Itä (east) reuna: x = x_max
        east_points = np.array([[y, self.region.x_max] for y in y_fine])
        bc['east'] = {
            'u': interpolators['u'](east_points),
            'v': interpolators['v'](east_points),
            'p': interpolators['p'](east_points)
        }
        
        # Etelä (south) reuna: y = y_min
        south_points = np.array([[self.region.y_min, x] for x in x_fine])
        bc['south'] = {
            'u': interpolators['u'](south_points),
            'v': interpolators['v'](south_points),
            'p': interpolators['p'](south_points)
        }
        
        # Pohjoinen (north) reuna: y = y_max
        north_points = np.array([[self.region.y_max, x] for x in x_fine])
        bc['north'] = {
            'u': interpolators['u'](north_points),
            'v': interpolators['v'](north_points),
            'p': interpolators['p'](north_points)
        }
        
        # Turbulenssisuureet
        for var in ['k', 'omega', 'epsilon']:
            if var in interpolators:
                bc['west'][var] = interpolators[var](west_points)
                bc['east'][var] = interpolators[var](east_points)
                bc['south'][var] = interpolators[var](south_points)
                bc['north'][var] = interpolators[var](north_points)
        
        return bc
    
    def _extract_fine_obstacles(self) -> list:
        """Poimii esteet jotka ovat tiheän hilan alueella."""
        fine_obstacles = []
        solid_count = 0
        porous_count = 0
        
        for obs in self.coarse.obstacles:
            # Tarkista onko este alueella (osittainkin)
            if hasattr(obs, 'vertices') and obs.vertices is not None:
                xs = [v[0] for v in obs.vertices]
                ys = [v[1] for v in obs.vertices]
                obs_x_min, obs_x_max = min(xs), max(xs)
                obs_y_min, obs_y_max = min(ys), max(ys)
            else:
                obs_x_min, obs_x_max = obs.x_min, obs.x_max
                obs_y_min, obs_y_max = obs.y_min, obs.y_max
            
            # Tarkista päällekkäisyys
            if (obs_x_max >= self.region.x_min and 
                obs_x_min <= self.region.x_max and
                obs_y_max >= self.region.y_min and 
                obs_y_min <= self.region.y_max):
                
                # Siirretään esteen koordinaatit suhteessa tiheän hilan origoon
                shifted_obs = self._shift_obstacle(obs)
                if shifted_obs is not None:
                    fine_obstacles.append(shifted_obs)
                    if hasattr(shifted_obs, 'is_solid') and not shifted_obs.is_solid:
                        porous_count += 1
                    else:
                        solid_count += 1
        
        if porous_count > 0:
            print(f"  Esteitä: {solid_count} kiinteää, {porous_count} huokoista (porous)")
        
        return fine_obstacles
    
    def _shift_obstacle(self, obs):
        """
        Luo uuden esteen siirretyillä koordinaateilla tiheän hilan koordinaatistoon.
        
        Tiheä hila alkaa origosta (0,0), joten esteiden koordinaatit
        pitää siirtää: new_x = old_x - region.x_min
        """
        # Siirtymä
        dx = self.region.x_min
        dy = self.region.y_min
        
        # Luo uusi este tyypin mukaan
        try:
            # Tarkista onko huokoinen vai kiinteä este
            is_porous = hasattr(obs, 'is_solid') and not obs.is_solid
            
            if hasattr(obs, 'vertices') and obs.vertices is not None:
                shifted_vertices = [(v[0] - dx, v[1] - dy) for v in obs.vertices]
                name = obs.name if hasattr(obs, 'name') else ""
                
                if is_porous:
                    # Huokoinen polygoni-este (TreeZone)
                    from geometry.obstacles import TreeZone
                    
                    return TreeZone(
                        vertices_list=shifted_vertices,
                        porosity=getattr(obs, 'porosity', 0.4),
                        height=getattr(obs, 'height', 15.0),
                        drag_coefficient=getattr(obs, 'drag_coefficient', 0.5),
                        vegetation_type=getattr(obs, 'vegetation_type', 'tree_zone'),
                        name=name
                    )
                else:
                    # Kiinteä polygoni-rakennus
                    from geometry.obstacles import PolygonBuilding
                    poly = PolygonBuilding(vertices_list=shifted_vertices, name=name)
                    poly.is_target = getattr(obs, 'is_target', False)
                    return poly
                
            elif hasattr(obs, 'x_center') and hasattr(obs, 'radius'):
                # Puu tai ympyrä-este
                from geometry.obstacles import Tree
                
                return Tree(
                    x_center=obs.x_center - dx,
                    y_center=obs.y_center - dy,
                    radius=obs.radius,
                    porosity=getattr(obs, 'porosity', 0.5),
                    drag_coefficient=getattr(obs, 'drag_coefficient', 0.5),
                    name=getattr(obs, 'name', "")
                )
                
            elif hasattr(obs, 'x_min') and hasattr(obs, 'x_max'):
                # Suorakaide-rakennus
                from geometry.obstacles import Building
                
                bldg = Building(
                    x_min=obs.x_min - dx,
                    x_max=obs.x_max - dx,
                    y_min=obs.y_min - dy,
                    y_max=obs.y_max - dy,
                    name=getattr(obs, 'name', "")
                )
                bldg.is_target = getattr(obs, 'is_target', False)
                return bldg
            else:
                print(f"  Varoitus: Tuntematon estetyyppi, ohitetaan: {type(obs)}")
                return None
                
        except Exception as e:
            print(f"  Varoitus: Esteen siirto epäonnistui: {e}")
            return None
    
    def solve(self, verbose: bool = True) -> 'NestedGridSolver':
        """
        Ratkaisee tiheän hilan käyttäen karkeaa ratkaisua reunaehtoina.
        
        Args:
            verbose: Tulosta edistyminen
            
        Returns:
            self (ketjutettavuutta varten)
        """
        print("\n" + "="*60)
        print("NESTED GRID - TIHEÄN HILAN RATKAISU")
        print("="*60)
        
        # 1. Luo interpolaattorit
        print("\nInterpoloidaan reunaehdot karkeasta ratkaisusta...")
        interpolators = self._create_interpolators()
        bc_data = self._interpolate_boundary_conditions(interpolators)
        
        # 2. Luo tiheä domain ja solver
        print("Luodaan tiheä hila...")
        
        # Importit projektin rakenteen mukaan
        from geometry.domain import Domain
        from solvers.cfd_solver import CFDSolver, SolverSettings
        from boundary_conditions.boundary import BoundaryConditions, FluidProperties
        from nested_boundary_conditions import NestedBoundaryConditions
        
        # Luo tiheä domain
        fine_domain = Domain(
            width=self.region.width,
            height=self.region.height,
            nx=self.fine_nx,
            ny=self.fine_ny
        )
        
        # Poimi esteet tiheälle alueelle
        fine_obstacles = self._extract_fine_obstacles()
        print(f"  Esteitä tiheällä alueella: {len(fine_obstacles)}")
        
        # Luo nested-reunaehdot
        fine_bc = NestedBoundaryConditions(
            bc_data=bc_data,
            inlet_velocity=self.coarse.bc.inlet_velocity,
            region_offset=(self.region.x_min, self.region.y_min)
        )
        
        # Luo fluid-olio (kopioi karkeasta)
        fine_fluid = FluidProperties(
            density=self.coarse.fluid.density,
            viscosity=self.coarse.fluid.viscosity
        )
        
        # Luo settings (kopioi karkeasta)
        fine_settings = SolverSettings(
            max_iterations=self.coarse.settings.max_iterations,
            convergence_tolerance=self.coarse.settings.convergence_tolerance,
            turbulence_model=self.coarse.model_type,
            pressure_iterations=self.coarse.settings.pressure_iterations,
            print_interval=self.coarse.settings.print_interval,
            use_wall_functions=self.coarse.settings.use_wall_functions
        )
        
        # Luo ja konfiguroi tiheä solver
        # Huom: NestedBoundaryConditions pitää wrappata BoundaryConditions-yhteensopivaksi
        from boundary_conditions.boundary import BoundaryConditions
        
        # Luo tavallinen BC tiheälle hilalle (nested BC asetetaan erikseen)
        fine_bc_standard = BoundaryConditions(
            inlet_velocity=self.coarse.bc.inlet_velocity,
            inlet_direction=self.coarse.bc.inlet_direction,
            turbulence_intensity=self.coarse.bc.turbulence_intensity
        )
        
        self.fine = CFDSolver(
            domain=fine_domain,
            fluid=fine_fluid,
            bc=fine_bc_standard,
            settings=fine_settings
        )
        
        # Tallenna nested BC myöhempää käyttöä varten
        self.fine_nested_bc = fine_bc
        
        # Lisää esteet (optimoitu: päivitä maskit vain kerran lopussa)
        n_obstacles = len(fine_obstacles)
        print(f"  Lisätään {n_obstacles} estettä tiheälle hilalle...")
        for i, obs in enumerate(fine_obstacles):
            # Lisää este ILMAN maskien päivitystä
            self.fine.obstacles.append(obs)
            # Näytä eteneminen joka 20. este tai viimeinen
            if (i + 1) % 20 == 0 or i == n_obstacles - 1:
                print(f"    Esteitä lisätty: {i + 1}/{n_obstacles}", end='\r')
        print()  # Uusi rivi
        
        # Päivitä maskit KERRAN kaikkien esteiden jälkeen
        print("  Päivitetään estemaskit...")
        self.fine._update_masks()
        print("  Maskit päivitetty.")
        
        # 3. Alusta tiheä hila interpoloiduilla arvoilla
        print("Alustetaan tiheä hila interpoloiduilla arvoilla...")
        print(f"  Fine turb_model olemassa: {hasattr(self.fine, 'turb_model') and self.fine.turb_model is not None}")
        if hasattr(self.fine, 'turb_model') and self.fine.turb_model is not None:
            print(f"  Fine k ennen alustusta: mean={self.fine.turb_model.k.mean():.2e}")
        print("  Interpoloidaan kenttiä...")
        self._initialize_fine_from_coarse(interpolators)
        print("  Interpolointi valmis.")
        if hasattr(self.fine, 'turb_model') and self.fine.turb_model is not None:
            print(f"  Fine k JÄLKEEN alustuksen: mean={self.fine.turb_model.k.mean():.2e}")
        
        # 4. Ratkaise tiheä hila MUKAUTETULLA ratkaisijalla
        # joka soveltaa nested-reunaehtoja joka iteraatiolla
        print(f"\nRatkaistaan tiheä hila...")
        
        # Debug: tarkista solid_mask
        solid_count = self.fine.solid_mask.sum()
        total_count = self.fine.solid_mask.size
        solid_fraction = solid_count / total_count
        print(f"  Solid mask: {solid_count}/{total_count} = {solid_fraction*100:.1f}% hilasta on kiinteää")
        
        # Debug: tarkista turbulenssimallin solid_mask
        if hasattr(self.fine.turb_model, 'solid_mask'):
            tm_solid = self.fine.turb_model.solid_mask.sum()
            tm_total = self.fine.turb_model.solid_mask.size
            print(f"  Turb model solid_mask: {tm_solid}/{tm_total} = {tm_solid/tm_total*100:.1f}%")
        
        self._solve_fine_with_nested_bc(verbose=verbose)
        
        return self
    
    def _solve_fine_with_nested_bc(self, verbose: bool = True) -> bool:
        """
        Ratkaisee tiheän hilan SIMPLE-algoritmilla, soveltaen 
        nested-reunaehtoja joka iteraatiolla.
        """
        solver = self.fine
        nested_bc = self.fine_nested_bc
        
        # Laske wall_dist KERRAN ennen iterointia (jos SST ja ei vielä laskettu)
        if solver.turb_model is not None and solver.model_type == "sst":
            if not getattr(solver.turb_model, '_wall_dist_computed', False):
                solver.turb_model.set_masks(solver.solid_mask, solver.porous_mask,
                                           solver.domain.dx, solver.domain.dy,
                                           drag_field=solver.drag_field)
        
        if verbose:
            print(f"TIHEÄ HILA - CFD-ratkaisu ({solver.model_type} turbulenssimalli)")
            print(f"Hila: {solver.domain.nx} × {solver.domain.ny}, dx={solver.domain.dx:.2f} m")
            print(f"Tuulennopeus: {solver.bc.inlet_velocity:.1f} m/s, suunta: {solver.bc.inlet_direction:.0f}°")
            print(f"Turbulenssi-intensiteetti: {solver.bc.turbulence_intensity*100:.1f}%")
            # Näytä wall functions tila sekä settings:stä että turbulenssimallista
            wf_settings = solver.settings.use_wall_functions
            wf_model = solver.turb_model.use_wall_functions if solver.turb_model and hasattr(solver.turb_model, 'use_wall_functions') else 'N/A'
            print(f"Wall functions: settings={wf_settings}, turb_model={wf_model} {'(SCALABLE)' if wf_settings and wf_model else ''}")
            print(f"Esteitä: {len(solver.obstacles)} (kiinteitä: {solver.solid_mask.sum()}, huokoisia: {solver.porous_mask.sum()} solua)")
            print("-" * 50)
        
        for iteration in range(solver.settings.max_iterations):
            # SIMPLE-iteraatio
            dt = solver._solve_momentum()
            solver._solve_pressure()
            solver._correct_fields()
            
            # NESTED REUNAEHDOT nopeuksille ja paineelle
            nested_bc.apply(solver)
            nested_bc.apply_pressure(solver)
            
            # Kiinteät esteet: no-slip
            solver.u[solver.solid_mask] = 0
            solver.v[solver.solid_mask] = 0
            
            # HUOM: Turbulenssin reunaehtoja EI pakoteta joka iteraatiolla!
            # _use_fixed_boundaries lippu estää SST:n Neumann-ylikirjoituksen,
            # ja reunat säilyvät alustuksen interpoloiduista arvoista.
            
            # Turbulenssi (ratkaise yhtälöt)
            solver._solve_turbulence(dt)
            
            # Konvergenssi
            residual = solver._calculate_residual()
            
            if verbose and iteration % solver.settings.print_interval == 0:
                if solver.turb_model is not None:
                    nu_t_arr = solver.turb_model.get_turbulent_viscosity()
                    nu_t_max = nu_t_arr.max()
                    nu_t_mean = nu_t_arr.mean()
                    k_max = solver.turb_model.k.max() if hasattr(solver.turb_model, 'k') else 0
                    k_mean = solver.turb_model.k.mean() if hasattr(solver.turb_model, 'k') else 0
                    omega_mean = solver.turb_model.omega.mean() if hasattr(solver.turb_model, 'omega') else 0
                    F2_mean = solver.turb_model.F2.mean() if hasattr(solver.turb_model, 'F2') else 0
                    # Laske teoreettinen nu_t
                    nu_t_theory = 0.31 * k_mean / max(0.31 * omega_mean, 1e-10)
                    print(f"Iter {iteration}: res={residual:.2e}, ν_t_max={nu_t_max:.2e}, k_mean={k_mean:.2e}, ω_mean={omega_mean:.2e}, F2={F2_mean:.3f}, ν_t_theory={nu_t_theory:.2e}")
                else:
                    print(f"Iter {iteration}: res={residual:.2e}")
                    
            if residual < solver.settings.convergence_tolerance:
                if verbose:
                    print(f"\nKonvergenssi saavutettu iteraatiolla {iteration}")
                return True
                
        if verbose:
            print(f"\nMaksimi-iteraatiot ({solver.settings.max_iterations}) saavutettu")
        return False
    
    def _smooth_field_simple(self, field: np.ndarray, solid_mask: np.ndarray, 
                             alpha: float = 0.2) -> np.ndarray:
        """
        Kevyt Laplacian-smoothing kentälle.
        
        Args:
            field: Kenttä jota smoothataan
            solid_mask: Kiinteiden alueiden maski
            alpha: Smoothing-kerroin (0-1, suurempi = enemmän smoothausta)
        
        Returns:
            Smoothattu kenttä
        """
        ny, nx = field.shape
        result = field.copy()
        
        for j in range(1, ny-1):
            for i in range(1, nx-1):
                if solid_mask[j, i]:
                    continue
                
                # Laske naapurien keskiarvo
                neighbors = 0.0
                count = 0
                
                for dj, di in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nj, ni = j + dj, i + di
                    if not solid_mask[nj, ni]:
                        neighbors += field[nj, ni]
                        count += 1
                
                if count > 0:
                    avg = neighbors / count
                    result[j, i] = (1.0 - alpha) * field[j, i] + alpha * avg
        
        return result
    
    def _initialize_fine_from_coarse(self, interpolators: Dict):
        """Alustaa tiheän hilan kentät interpoloimalla karkeasta."""
        # Tiheän hilan koordinaattiruudukko (absoluuttisina koordinaatteina)
        x_fine = np.linspace(self.region.x_min, self.region.x_max, self.fine_nx)
        y_fine = np.linspace(self.region.y_min, self.region.y_max, self.fine_ny)
        X_fine, Y_fine = np.meshgrid(x_fine, y_fine)
        
        # Interpolointipisteet
        points = np.column_stack([Y_fine.ravel(), X_fine.ravel()])
        
        # Interpoloi nopeuskentät (u, v) KOKO hilalle
        self.fine.u = interpolators['u'](points).reshape(self.fine_ny, self.fine_nx)
        self.fine.v = interpolators['v'](points).reshape(self.fine_ny, self.fine_nx)
        
        # Paine: interpoloi VAIN REUNOILLE, sisäkenttä nollaksi
        # SIMPLE-menetelmä korjaa paineen iteraatioissa
        # Tämä estää checkerboard-virheiden siirtymisen karkeasta hilasta
        border_width_p = min(10, self.fine_nx // 6, self.fine_ny // 6)
        p_interp = interpolators['p'](points).reshape(self.fine_ny, self.fine_nx)
        
        # Luo reunamaski paineelle
        border_mask_p = np.zeros((self.fine_ny, self.fine_nx), dtype=bool)
        border_mask_p[:border_width_p, :] = True
        border_mask_p[-border_width_p:, :] = True
        border_mask_p[:, :border_width_p] = True
        border_mask_p[:, -border_width_p:] = True
        
        # Sisäkenttä nollaksi, reunat interpoloidusta
        self.fine.p = np.zeros((self.fine_ny, self.fine_nx))
        self.fine.p[border_mask_p] = p_interp[border_mask_p]
        
        # Smoothaa nopeuskentät checkerboard-virheiden poistamiseksi
        # Käytetään kevyttä Laplacian-smoothingia (3 kierrosta)
        for _ in range(3):
            self.fine.u = self._smooth_field_simple(self.fine.u, self.fine.solid_mask)
            self.fine.v = self._smooth_field_simple(self.fine.v, self.fine.solid_mask)
        
        print(f"    u interpoloitu+smoothattu: min={self.fine.u.min():.2f}, max={self.fine.u.max():.2f}")
        print(f"    v interpoloitu+smoothattu: min={self.fine.v.min():.2f}, max={self.fine.v.max():.2f}")
        print(f"    p: reunat interpoloitu ({border_width_p} solua), sisäkenttä=0")
        
        # Turbulenssi: interpoloi VAIN REUNAVYÖHYKKEELLE
        # Sisäkenttä käyttää tasaisia freestream-arvoja ja saa kehittyä vapaasti.
        # Tämä estää karkean hilan checkerboard-virheiden siirtymisen tiheään hilaan.
        if hasattr(self.fine, 'turb_model') and self.fine.turb_model is not None:
            tm = self.fine.turb_model
            
            # Reunavyöhykkeen leveys (soluja) - riittävän leveä reunaehtoihin
            border_width = min(15, self.fine_nx // 4, self.fine_ny // 4)
            
            if self.coarse.turb_model is not None and 'k' in interpolators and 'omega' in interpolators:
                # Interpoloi k ja omega KOKO kentälle karkeasta hilasta
                k_interp = interpolators['k'](points).reshape(self.fine_ny, self.fine_nx)
                k_interp = np.maximum(k_interp, 1e-6)
                
                omega_interp = interpolators['omega'](points).reshape(self.fine_ny, self.fine_nx)
                omega_interp = np.maximum(omega_interp, 0.1)  # Pieni alaraja
                
                # HUOM: Omega rajoitus poistettu - ei tarpeen kun omega_wall kaava on korjattu
                # Menter log-law omega_wall antaa järkevät arvot (~1-10 lähellä seiniä)
                
                # Aseta KOKO kenttä
                non_solid = ~self.fine.solid_mask
                tm.k[non_solid] = k_interp[non_solid]
                tm.omega[non_solid] = omega_interp[non_solid]
                
                # TÄRKEÄ: Estä SST:n Neumann-reunaehtojen ylikirjoitus nested-hilassa
                tm._use_fixed_boundaries = True
                
                # Debug-tulostus
                omega_valid = omega_interp[non_solid]
                k_valid = k_interp[non_solid]
                print(f"    k: interpoloitu KOKO kenttä karkeasta")
                print(f"       min={k_valid.min():.2e}, max={k_valid.max():.2e}, mean={k_valid.mean():.2e}")
                print(f"    omega: interpoloitu KOKO kenttä karkeasta")
                print(f"       min={omega_valid.min():.1f}, max={omega_valid.max():.1f}, mean={omega_valid.mean():.1f}")
                print(f"    _use_fixed_boundaries = True")
            else:
                print(f"    Turbulenssi: käytetään standardialustusta (ei interpolointia)")
            
            # Aseta kiinteisiin soluihin oikeat arvot
            tm.k[self.fine.solid_mask] = tm.const.k_min
            tm.omega[self.fine.solid_mask] = tm.const.omega_min
            
            # Päivitä nu_t
            if hasattr(tm, '_update_blending_functions'):
                tm._update_blending_functions()
            if hasattr(tm, '_update_turbulent_viscosity'):
                tm._update_turbulent_viscosity(self.fine.u, self.fine.v, 
                                               self.fine.domain.dx, self.fine.domain.dy)
            
            print(f"    nu_t alustuksen jälkeen: mean={tm.nu_t.mean():.2e}")
    
    def get_combined_results(self) -> Dict[str, np.ndarray]:
        """
        Palauttaa yhdistetyt tulokset (karkea + tiheä).
        
        Tiheän hilan tulokset korvaavat karkean hilan tulokset
        päällekkäisellä alueella.
        """
        if self.fine is None:
            raise RuntimeError("Fine grid not solved yet. Call solve() first.")
        
        # Kopioi karkeat tulokset
        results = {
            'u': self.coarse.u.copy(),
            'v': self.coarse.v.copy(),
            'p': self.coarse.p.copy(),
            'vel': self.coarse.get_velocity_magnitude().copy()
        }
        
        # Laske indeksit missä tiheä hila sijaitsee karkeassa
        i_min = int(self.region.x_min / self.coarse.domain.dx)
        i_max = int(self.region.x_max / self.coarse.domain.dx)
        j_min = int(self.region.y_min / self.coarse.domain.dy)
        j_max = int(self.region.y_max / self.coarse.domain.dy)
        
        # Interpoloi tiheästä takaisin karkeaan resoluutioon päällekkäiselle alueelle
        # (yksinkertainen downsampling)
        from scipy.ndimage import zoom
        
        target_shape = (j_max - j_min, i_max - i_min)
        
        for key in ['u', 'v', 'p']:
            fine_data = getattr(self.fine, key)
            zoom_factors = (target_shape[0] / fine_data.shape[0],
                          target_shape[1] / fine_data.shape[1])
            downsampled = zoom(fine_data, zoom_factors, order=1)
            results[key][j_min:j_max, i_min:i_max] = downsampled
        
        # Päivitä nopeus
        results['vel'] = np.sqrt(results['u']**2 + results['v']**2)
        
        return results
    
    def get_fine_results(self) -> Optional['CFDSolver']:
        """Palauttaa tiheän hilan solverin."""
        return self.fine
    
    def get_coarse_results(self) -> 'CFDSolver':
        """Palauttaa karkean hilan solverin."""
        return self.coarse


class NestedBoundaryConditions:
    """
    Reunaehdot nested grid -simulointiin.
    
    Käyttää interpoloituja arvoja karkeasta hilasta reunaehtoina.
    """
    
    def __init__(self, 
                 bc_data: Dict[str, Dict[str, np.ndarray]],
                 inlet_velocity: float,
                 region_offset: Tuple[float, float] = (0, 0)):
        """
        Args:
            bc_data: Interpoloidut reunaehdot karkeasta hilasta
            inlet_velocity: Referenssinopeus (skaalausta varten)
            region_offset: Tiheän alueen siirtymä (x_min, y_min)
        """
        self.bc_data = bc_data
        self.inlet_velocity = inlet_velocity
        self.region_offset = region_offset
        self.wind_direction = 270  # Oletus länsi
    
    def apply(self, solver):
        """Asettaa reunaehdot tiheälle hilalle."""
        ny, nx = solver.u.shape
        
        # Länsi (inlet tai interpoloitu)
        if 'west' in self.bc_data:
            solver.u[:, 0] = self.bc_data['west']['u']
            solver.v[:, 0] = self.bc_data['west']['v']
        
        # Itä (outlet tai interpoloitu)
        if 'east' in self.bc_data:
            solver.u[:, -1] = self.bc_data['east']['u']
            solver.v[:, -1] = self.bc_data['east']['v']
        
        # Etelä
        if 'south' in self.bc_data:
            solver.u[0, :] = self.bc_data['south']['u']
            solver.v[0, :] = self.bc_data['south']['v']
        
        # Pohjoinen
        if 'north' in self.bc_data:
            solver.u[-1, :] = self.bc_data['north']['u']
            solver.v[-1, :] = self.bc_data['north']['v']
    
    def apply_turbulence(self, turb_model, solver):
        """Asettaa turbulenssin reunaehdot."""
        if turb_model is None:
            return
        
        # k-kenttä
        if hasattr(turb_model, 'k') and 'k' in self.bc_data.get('west', {}):
            turb_model.k[:, 0] = self.bc_data['west']['k']
            turb_model.k[:, -1] = self.bc_data['east']['k']
            turb_model.k[0, :] = self.bc_data['south']['k']
            turb_model.k[-1, :] = self.bc_data['north']['k']
        
        # omega-kenttä (SST)
        if hasattr(turb_model, 'omega') and 'omega' in self.bc_data.get('west', {}):
            turb_model.omega[:, 0] = self.bc_data['west']['omega']
            turb_model.omega[:, -1] = self.bc_data['east']['omega']
            turb_model.omega[0, :] = self.bc_data['south']['omega']
            turb_model.omega[-1, :] = self.bc_data['north']['omega']


def solve_nested(coarse_config: Dict[str, Any],
                 fine_bounds: Tuple[float, float, float, float],
                 refinement: int = 4,
                 coarse_iterations: int = 400,
                 fine_iterations: int = 500) -> NestedGridSolver:
    """
    Korkean tason funktio nested grid -simulointiin.
    
    Args:
        coarse_config: Karkean simuloinnin konfiguraatio
        fine_bounds: Tiheän alueen rajat (x_min, x_max, y_min, y_max)
        refinement: Tihennyskerroin
        coarse_iterations: Karkean hilan iteraatiot
        fine_iterations: Tiheän hilan iteraatiot
        
    Returns:
        NestedGridSolver ratkaistuna
        
    Example:
        >>> nested = solve_nested(
        ...     coarse_config={'geometry': 'area.json', 'resolution': 1.0},
        ...     fine_bounds=(100, 250, 50, 200),
        ...     refinement=4
        ... )
        >>> fine_solver = nested.get_fine_results()
    """
    # Tämä on placeholder - täysi toteutus vaatii integroinnin
    # olemassa olevaan main.py -rakenteeseen
    raise NotImplementedError(
        "Käytä NestedGridSolver-luokkaa suoraan tai "
        "main.py --nested parametria"
    )


# Apufunktiot visualisointiin

def _add_obstacles_shifted(ax, obstacles, x_offset: float, y_offset: float):
    """
    Piirtää esteet siirretyillä koordinaateilla.
    
    Args:
        ax: Matplotlib axis
        obstacles: Lista esteistä (tiheän hilan koordinaateissa)
        x_offset: X-siirtymä (lisätään koordinaatteihin)
        y_offset: Y-siirtymä (lisätään koordinaatteihin)
    """
    import matplotlib.patches as patches
    from matplotlib.patches import Polygon as MplPolygon
    
    for obs in obstacles:
        # Määritä väri ja tyyli estetyypin mukaan
        is_solid = getattr(obs, 'is_solid', True)
        if is_solid:
            # Kiinteä rakennus - harmaa täyttö, korkea zorder
            is_target = getattr(obs, 'is_target', False)
            if is_target:
                facecolor, edgecolor, alpha, lw, zorder = '#4a4a4a', '#d32f2f', 0.9, 2.5, 20
            else:
                facecolor, edgecolor, alpha, lw, zorder = '#404040', 'black', 0.9, 1.5, 20
        else:
            # Kasvillisuus/tiealue - matala zorder
            veg_type = getattr(obs, 'vegetation_type', None) or getattr(obs, 'obs_type', 'tree_zone')
            if veg_type == 'road':
                facecolor, edgecolor, alpha, lw, zorder = '#909090', '#606060', 0.7, 1.2, 3  # Harmaa tie
            elif veg_type in ('water', 'lake', 'pond', 'river'):
                facecolor, edgecolor, alpha, lw, zorder = '#a8d4f0', '#4a90c4', 0.35, 1.2, 2  # Sininen vesi
            elif veg_type == 'farmland':
                facecolor, edgecolor, alpha, lw, zorder = '#FFE082', '#B8860B', 0.3, 2, 2  # Kellertävä pelto
            else:
                facecolor, edgecolor, alpha, lw, zorder = '#90EE90', '#228b22', 0.3, 2, 2  # Vihreä kasvillisuus
        
        if hasattr(obs, 'vertices') and obs.vertices is not None:
            # Siirrä verteksit takaisin absoluuttisiin koordinaatteihin
            shifted_vertices = [(v[0] + x_offset, v[1] + y_offset) for v in obs.vertices]
            poly = MplPolygon(shifted_vertices, facecolor=facecolor, 
                             edgecolor=edgecolor, linewidth=lw, alpha=alpha, zorder=zorder)
            ax.add_patch(poly)
        elif hasattr(obs, 'x_min'):
            # Suorakaide
            rect = patches.Rectangle(
                (obs.x_min + x_offset, obs.y_min + y_offset),
                obs.x_max - obs.x_min,
                obs.y_max - obs.y_min,
                facecolor=facecolor, edgecolor=edgecolor, linewidth=lw, alpha=alpha, zorder=zorder
            )
            ax.add_patch(rect)


def plot_nested_comparison(nested: NestedGridSolver, 
                           output_dir: str,
                           dpi: int = 150):
    """
    Piirtää vertailukuvan karkeasta ja tiheästä hilasta yhdistettynä.
    """
    import matplotlib.pyplot as plt
    from pathlib import Path
    
    if nested.fine is None:
        raise RuntimeError("Fine grid not solved")
    
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))
    
    # Karkean hilan data
    X_c, Y_c = nested.coarse.domain.X, nested.coarse.domain.Y
    vel_c = nested.coarse.get_velocity_magnitude()
    
    # Tiheän hilan data
    X_f, Y_f = nested.fine.domain.X, nested.fine.domain.Y
    X_f_abs = X_f + nested.region.x_min
    Y_f_abs = Y_f + nested.region.y_min
    vel_f = nested.fine.get_velocity_magnitude()
    
    # Yhteinen väriskaalaus
    vmin = min(vel_c.min(), vel_f.min())
    vmax = max(vel_c.max(), vel_f.max())
    levels = np.linspace(vmin, vmax, 30)
    
    # Karkea taustalla (himmennetty)
    ax.contourf(X_c, Y_c, vel_c, levels=levels, cmap='viridis', alpha=0.4)
    
    # Tiheä päällä (täysi väri)
    im = ax.contourf(X_f_abs, Y_f_abs, vel_f, levels=levels, cmap='viridis')
    plt.colorbar(im, ax=ax, label='Nopeus [m/s]')
    
    # Piirretään karkean hilan esteet
    _add_obstacles_shifted(ax, nested.coarse.obstacles, 0, 0)
    
    # Tiheän alueen rajat
    rect = plt.Rectangle(
        (nested.region.x_min, nested.region.y_min),
        nested.region.width, nested.region.height,
        fill=False, edgecolor='red', linewidth=2
    )
    ax.add_patch(rect)
    
    # Laske hilakoot
    coarse_dx = nested.coarse.domain.width / nested.coarse.domain.nx
    fine_dx = coarse_dx / nested.region.refinement
    
    ax.set_title(f'Nested-simulointi: karkea {coarse_dx:.1f}m hila + tiheä {fine_dx:.2f}m hila ({nested.region.refinement}× tihennys)')
    ax.set_xlabel('x [m]')
    ax.set_ylabel('y [m]')
    ax.set_aspect('equal')
    
    # Rajaa kuva karkean hilan alueelle (estää viheralueiden ulottumisen yli)
    ax.set_xlim(X_c.min(), X_c.max())
    ax.set_ylim(Y_c.min(), Y_c.max())
    
    plt.tight_layout()
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filepath = output_path / 'nested_comparison.png'
    plt.savefig(filepath, dpi=dpi, bbox_inches='tight')
    plt.close(fig)
    
    print(f"  ✓ {filepath.name}")
    return str(filepath)


def plot_nested_detail(nested: NestedGridSolver,
                       output_dir: str, 
                       show_streamlines: bool = True,
                       dpi: int = 150):
    """
    Piirtää yksityiskohtaisen kuvan tiheästä hilasta.
    """
    import matplotlib.pyplot as plt
    from pathlib import Path
    
    if nested.fine is None:
        raise RuntimeError("Fine grid not solved")
    
    fig, ax = plt.subplots(figsize=(12, 10))
    
    X_f, Y_f = nested.fine.domain.X, nested.fine.domain.Y
    X_f_abs = X_f + nested.region.x_min
    Y_f_abs = Y_f + nested.region.y_min
    
    vel_f = nested.fine.get_velocity_magnitude()
    
    v_max = nested.coarse.bc.inlet_velocity * 1.6
    levels = np.linspace(0, v_max, 40)
    
    im = ax.contourf(X_f_abs, Y_f_abs, vel_f, levels=levels, cmap='viridis', extend='max')
    plt.colorbar(im, ax=ax, label='Nopeus [m/s]')
    
    # Esteet
    for obs in nested.fine.obstacles:
        # Määritä väri estetyypin mukaan
        is_solid = getattr(obs, 'is_solid', True)
        if is_solid:
            facecolor, edgecolor, alpha = '#404040', 'black', 0.9
        else:
            veg_type = getattr(obs, 'vegetation_type', None) or getattr(obs, 'obs_type', 'tree_zone')
            if veg_type == 'farmland':
                facecolor, edgecolor, alpha = '#FFE082', '#DAA520', 0.6
            else:
                facecolor, edgecolor, alpha = '#228b22', '#1a6b1a', 0.5
        
        if hasattr(obs, 'vertices') and obs.vertices is not None:
            from matplotlib.patches import Polygon
            poly = Polygon(obs.vertices, facecolor=facecolor, 
                          edgecolor=edgecolor, linewidth=1, alpha=alpha)
            ax.add_patch(poly)
    
    # Virtaviivat
    if show_streamlines:
        u_plot = nested.fine.u.copy()
        v_plot = nested.fine.v.copy()
        u_plot[nested.fine.solid_mask] = np.nan
        v_plot[nested.fine.solid_mask] = np.nan
        
        try:
            ax.streamplot(X_f_abs, Y_f_abs, u_plot, v_plot,
                         color='white', linewidth=0.5, density=2.5)
        except:
            pass
    
    ax.set_xlim(nested.region.x_min, nested.region.x_max)
    ax.set_ylim(nested.region.y_min, nested.region.y_max)
    ax.set_aspect('equal')
    ax.set_xlabel('x [m]')
    ax.set_ylabel('y [m]')
    ax.set_title(f'Tiheä hila - {nested.region.refinement}× tihennys '
                f'(dx={nested.fine_dx:.2f} m)')
    
    plt.tight_layout()
    
    output_path = Path(output_dir)
    filepath = output_path / 'nested_fine_detail.png'
    plt.savefig(filepath, dpi=dpi, bbox_inches='tight')
    plt.close(fig)
    
    print(f"  ✓ {filepath.name}")
    return str(filepath)
