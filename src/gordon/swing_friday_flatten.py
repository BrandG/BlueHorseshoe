"""BH Swing — scheduled Friday-close flatten entrypoint.

Thin wrapper around ``bh_swing.operator.friday_flatten`` so the script is
at the canonical location matching the other ``bh_swing_*.py`` tools.

Usage (cron):
  ./run.sh python src/bh_swing_friday_flatten.py

Usage (operator, manual override on non-Fridays):
  ./run.sh python src/bh_swing_friday_flatten.py --force
  ./run.sh python src/bh_swing_friday_flatten.py --dry-run
"""
import sys

from bh_swing.operator.friday_flatten import main


if __name__ == "__main__":
    sys.exit(main())
