"""BH Swing emergency flatten — top-level entrypoint.

Thin wrapper around bh_swing.operator.flatten so the script is at the
canonical location matching bh_ftmo_flatten.py.

Usage:
  ./run.sh python src/bh_swing_flatten.py
  ./run.sh python src/bh_swing_flatten.py --execute
  ./run.sh python src/bh_swing_flatten.py --execute --sort biggest --max-closes 3
  ./run.sh python src/bh_swing_flatten.py --symbols AAPL,MSFT --execute
"""
import sys

from bh_swing.operator.flatten import main


if __name__ == "__main__":
    sys.exit(main())
