from __future__ import annotations

from datetime import date

# Límites explícitos y amplios para que Streamlit no derive por defecto una
# ventana de sólo +/-10 años alrededor del valor inicial del calendario.
DATE_INPUT_MIN = date(1000, 1, 1)
DATE_INPUT_MAX = date(2500, 12, 31)
