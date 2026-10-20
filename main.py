"""Ponto de entrada: python main.py (ou o executável CadastroFormaSeg.exe)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cadastro_formaseg.gui import main  # noqa: E402

if __name__ == "__main__":
    main()
