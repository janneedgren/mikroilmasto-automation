"""
Nested Grid reunaehdot CFD-solverille.

Tämä moduuli lisätään core/boundary_conditions.py -tiedostoon
tai käytetään erillisenä.
"""

import numpy as np
from typing import Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class NestedBoundaryConditions:
    """
    Reunaehdot nested grid -simulointiin.
    
    Käyttää interpoloituja arvoja karkeasta hilasta reunaehtoina
    tiheälle alihilalle. Tämä mahdollistaa one-way coupling:
    karkea hila → tiheä hila.
    
    Attributes:
        bc_data: Interpoloidut reunaehdot karkeasta hilasta
                 {'west': {'u': array, 'v': array, ...}, 'east': {...}, ...}
        inlet_velocity: Referenssinopeus
        region_offset: Tiheän alueen siirtymä (x_min, y_min) suhteessa karkeaan
        wind_direction: Tuulen suunta (asteina, 0=pohjoinen, 90=itä, 270=länsi)
    """
    bc_data: Dict[str, Dict[str, np.ndarray]]
    inlet_velocity: float
    region_offset: Tuple[float, float] = (0.0, 0.0)
    wind_direction: float = 270.0
    
    def apply(self, solver) -> None:
        """
        Asettaa reunaehdot tiheälle hilalle interpoloiduista arvoista.
        
        Kutsutaan joka iteraatiolla ennen ratkaisua.
        
        Args:
            solver: CFDSolver-olio jolle reunaehdot asetetaan
        """
        ny, nx = solver.u.shape
        
        # Länsi (west) reuna - indeksi [:, 0]
        if 'west' in self.bc_data:
            west = self.bc_data['west']
            # Varmista että pituus täsmää
            if len(west['u']) == ny:
                solver.u[:, 0] = west['u']
                solver.v[:, 0] = west['v']
            else:
                # Interpoloi jos pituudet eivät täsmää
                solver.u[:, 0] = np.interp(
                    np.linspace(0, 1, ny),
                    np.linspace(0, 1, len(west['u'])),
                    west['u']
                )
                solver.v[:, 0] = np.interp(
                    np.linspace(0, 1, ny),
                    np.linspace(0, 1, len(west['v'])),
                    west['v']
                )
        
        # Itä (east) reuna - indeksi [:, -1]
        if 'east' in self.bc_data:
            east = self.bc_data['east']
            if len(east['u']) == ny:
                solver.u[:, -1] = east['u']
                solver.v[:, -1] = east['v']
            else:
                solver.u[:, -1] = np.interp(
                    np.linspace(0, 1, ny),
                    np.linspace(0, 1, len(east['u'])),
                    east['u']
                )
                solver.v[:, -1] = np.interp(
                    np.linspace(0, 1, ny),
                    np.linspace(0, 1, len(east['v'])),
                    east['v']
                )
        
        # Etelä (south) reuna - indeksi [0, :]
        if 'south' in self.bc_data:
            south = self.bc_data['south']
            if len(south['u']) == nx:
                solver.u[0, :] = south['u']
                solver.v[0, :] = south['v']
            else:
                solver.u[0, :] = np.interp(
                    np.linspace(0, 1, nx),
                    np.linspace(0, 1, len(south['u'])),
                    south['u']
                )
                solver.v[0, :] = np.interp(
                    np.linspace(0, 1, nx),
                    np.linspace(0, 1, len(south['v'])),
                    south['v']
                )
        
        # Pohjoinen (north) reuna - indeksi [-1, :]
        if 'north' in self.bc_data:
            north = self.bc_data['north']
            if len(north['u']) == nx:
                solver.u[-1, :] = north['u']
                solver.v[-1, :] = north['v']
            else:
                solver.u[-1, :] = np.interp(
                    np.linspace(0, 1, nx),
                    np.linspace(0, 1, len(north['u'])),
                    north['u']
                )
                solver.v[-1, :] = np.interp(
                    np.linspace(0, 1, nx),
                    np.linspace(0, 1, len(north['v'])),
                    north['v']
                )
    
    def apply_pressure(self, solver) -> None:
        """
        Asettaa paineen reunaehdot (Neumann tai interpoloitu).
        
        Args:
            solver: CFDSolver-olio
        """
        # Paine: käytä interpoloituja arvoja jos saatavilla,
        # muuten Neumann (nollagradientti)
        
        if 'west' in self.bc_data and 'p' in self.bc_data['west']:
            solver.p[:, 0] = self.bc_data['west']['p']
        else:
            solver.p[:, 0] = solver.p[:, 1]
        
        if 'east' in self.bc_data and 'p' in self.bc_data['east']:
            solver.p[:, -1] = self.bc_data['east']['p']
        else:
            solver.p[:, -1] = solver.p[:, -2]
        
        if 'south' in self.bc_data and 'p' in self.bc_data['south']:
            solver.p[0, :] = self.bc_data['south']['p']
        else:
            solver.p[0, :] = solver.p[1, :]
        
        if 'north' in self.bc_data and 'p' in self.bc_data['north']:
            solver.p[-1, :] = self.bc_data['north']['p']
        else:
            solver.p[-1, :] = solver.p[-2, :]
    
    def apply_turbulence(self, turb_model, solver) -> None:
        """
        Asettaa turbulenssin reunaehdot interpoloiduista arvoista.
        
        Args:
            turb_model: Turbulenssimalli (SSTModel, KEpsilonModel)
            solver: CFDSolver-olio
        """
        if turb_model is None:
            return
        
        ny, nx = solver.u.shape
        
        # k-kenttä (turbulenssin kineettinen energia)
        if hasattr(turb_model, 'k'):
            self._apply_turbulence_field(turb_model.k, 'k', ny, nx)
        
        # omega-kenttä (SST)
        if hasattr(turb_model, 'omega'):
            self._apply_turbulence_field(turb_model.omega, 'omega', ny, nx)
        
        # epsilon-kenttä (k-epsilon)
        if hasattr(turb_model, 'epsilon'):
            self._apply_turbulence_field(turb_model.epsilon, 'epsilon', ny, nx)
    
    def _apply_turbulence_field(self, field: np.ndarray, 
                                 var_name: str, 
                                 ny: int, nx: int) -> None:
        """Apufunktio turbulenssikenttien reunaehtojen asettamiseen."""
        
        for edge, idx in [('west', (slice(None), 0)), 
                          ('east', (slice(None), -1))]:
            if edge in self.bc_data and var_name in self.bc_data[edge]:
                data = self.bc_data[edge][var_name]
                if len(data) == ny:
                    field[idx] = data
                else:
                    field[idx] = np.interp(
                        np.linspace(0, 1, ny),
                        np.linspace(0, 1, len(data)),
                        data
                    )
        
        for edge, idx in [('south', (0, slice(None))), 
                          ('north', (-1, slice(None)))]:
            if edge in self.bc_data and var_name in self.bc_data[edge]:
                data = self.bc_data[edge][var_name]
                if len(data) == nx:
                    field[idx] = data
                else:
                    field[idx] = np.interp(
                        np.linspace(0, 1, nx),
                        np.linspace(0, 1, len(data)),
                        data
                    )
    
    def get_stats(self) -> Dict[str, float]:
        """Palauttaa reunaehtojen tilastot debuggausta varten."""
        stats = {}
        
        for edge in ['west', 'east', 'south', 'north']:
            if edge in self.bc_data:
                for var in ['u', 'v', 'p', 'k', 'omega']:
                    if var in self.bc_data[edge]:
                        data = self.bc_data[edge][var]
                        stats[f'{edge}_{var}_mean'] = np.mean(data)
                        stats[f'{edge}_{var}_max'] = np.max(data)
                        stats[f'{edge}_{var}_min'] = np.min(data)
        
        return stats


def interpolate_coarse_to_fine_bc(coarse_solver, 
                                   fine_region,
                                   fine_nx: int, 
                                   fine_ny: int) -> Dict[str, Dict[str, np.ndarray]]:
    """
    Interpoloi reunaehdot karkeasta ratkaisusta tiheälle hilalle.
    
    Args:
        coarse_solver: Ratkaistu karkea CFDSolver
        fine_region: NestedRegion-olio (x_min, x_max, y_min, y_max)
        fine_nx, fine_ny: Tiheän hilan solumäärät
        
    Returns:
        Dict reunaehdoista: {'west': {'u': array, ...}, 'east': {...}, ...}
    """
    from scipy.interpolate import RegularGridInterpolator
    
    # Karkean hilan koordinaatit
    x_coarse = np.linspace(0, coarse_solver.domain.width, coarse_solver.domain.nx)
    y_coarse = np.linspace(0, coarse_solver.domain.height, coarse_solver.domain.ny)
    
    # Luo interpolaattorit
    def make_interp(data):
        return RegularGridInterpolator(
            (y_coarse, x_coarse), data,
            method='linear', bounds_error=False, fill_value=None
        )
    
    interp_u = make_interp(coarse_solver.u)
    interp_v = make_interp(coarse_solver.v)
    interp_p = make_interp(coarse_solver.p)
    
    # Turbulenssikentät
    interp_turb = {}
    if coarse_solver.turb_model is not None:
        fields = coarse_solver.turb_model.get_turbulence_fields()
        for name, data in fields.items():
            if data is not None:
                interp_turb[name] = make_interp(data)
    
    # Tiheän hilan reunakoordinaatit
    x_fine = np.linspace(fine_region.x_min, fine_region.x_max, fine_nx)
    y_fine = np.linspace(fine_region.y_min, fine_region.y_max, fine_ny)
    
    bc_data = {}
    
    # Länsi reuna (x = x_min, y vaihtelee)
    west_pts = np.array([[y, fine_region.x_min] for y in y_fine])
    bc_data['west'] = {
        'u': interp_u(west_pts),
        'v': interp_v(west_pts),
        'p': interp_p(west_pts)
    }
    for name, interp in interp_turb.items():
        bc_data['west'][name] = interp(west_pts)
    
    # Itä reuna (x = x_max, y vaihtelee)
    east_pts = np.array([[y, fine_region.x_max] for y in y_fine])
    bc_data['east'] = {
        'u': interp_u(east_pts),
        'v': interp_v(east_pts),
        'p': interp_p(east_pts)
    }
    for name, interp in interp_turb.items():
        bc_data['east'][name] = interp(east_pts)
    
    # Etelä reuna (y = y_min, x vaihtelee)
    south_pts = np.array([[fine_region.y_min, x] for x in x_fine])
    bc_data['south'] = {
        'u': interp_u(south_pts),
        'v': interp_v(south_pts),
        'p': interp_p(south_pts)
    }
    for name, interp in interp_turb.items():
        bc_data['south'][name] = interp(south_pts)
    
    # Pohjoinen reuna (y = y_max, x vaihtelee)
    north_pts = np.array([[fine_region.y_max, x] for x in x_fine])
    bc_data['north'] = {
        'u': interp_u(north_pts),
        'v': interp_v(north_pts),
        'p': interp_p(north_pts)
    }
    for name, interp in interp_turb.items():
        bc_data['north'][name] = interp(north_pts)
    
    return bc_data
