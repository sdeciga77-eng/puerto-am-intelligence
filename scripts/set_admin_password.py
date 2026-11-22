"""Genera un hash PBKDF2 para ADMIN_PASSWORD_HASH sin guardar la contraseña.

Uso:
    python scripts/set_admin_password.py
    python scripts/set_admin_password.py "MiContraseñaSegura"
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.security import hash_password  # noqa: E402


def main() -> int:
    password = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("Nueva contraseña del panel: ")
    if len(password) < 12:
        print("ERROR: usa al menos 12 caracteres.", file=sys.stderr)
        return 1
    confirmation = getpass.getpass("Repite la contraseña: ") if len(sys.argv) == 1 else password
    if password != confirmation:
        print("ERROR: las contraseñas no coinciden.", file=sys.stderr)
        return 1
    print("\nAgrega esta línea a tu .env (o variable de entorno) y reinicia el servidor:\n")
    print(f"ADMIN_PASSWORD_HASH={hash_password(password)}\n")
    print("La contraseña en texto plano NO se guarda ni se muestra.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
