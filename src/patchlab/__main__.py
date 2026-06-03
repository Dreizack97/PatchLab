"""Permite ejecutar la aplicación con ``python -m patchlab``."""

import sys

from patchlab.main import run

if __name__ == "__main__":
    sys.exit(run())
