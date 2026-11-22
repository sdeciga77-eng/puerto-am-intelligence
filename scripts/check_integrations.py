"""Muestra qué integraciones están realmente conectadas y cuáles faltan.

No hace falta iniciar el servidor: lee .env / variables de entorno.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import config  # noqa: E402


def main() -> int:
    print("=" * 72)
    print("PUERTO A&M | ESTADO DE INTEGRACIONES (desde configuración real)")
    print("=" * 72)
    connected = 0
    for key, item in config.INTEGRACIONES.items():
        state = "CONECTADO" if item["configurada"] else "PENDIENTE"
        connected += int(item["configurada"])
        print(f"[{state:>9}] {key:<16} {item['nombre']}")
        print(f"             {item['detalle']}")
    print("=" * 72)
    print(f"{connected}/{len(config.INTEGRACIONES)} canales configurados. Las integraciones pendientes NO se simulan.")
    if connected < len(config.INTEGRACIONES):
        print("Copia .env.example como .env y completa las variables N8N_* según tus workflows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
