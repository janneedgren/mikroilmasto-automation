"""
MikroilmastoCFD - QA (Quality Assurance) moduuli

Sisältää:
- logger.py: QALogger-luokka simulointien lokitukseen
- dashboard.py: HTML-dashboard validointitilastoille
"""

from .logger import QALogger
from .dashboard import update_dashboard, generate_dashboard_html

__all__ = ['QALogger', 'update_dashboard', 'generate_dashboard_html']
