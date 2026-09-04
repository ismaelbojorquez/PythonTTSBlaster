"""Run directly from the checkout with the environment's installed dependencies."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from blaster.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
