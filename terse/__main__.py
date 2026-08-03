"""``python -m terse`` — same entry point as the ``terse`` console script."""
import sys

from .audit import main

sys.exit(main())
