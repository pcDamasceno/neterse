"""``python -m neterse`` — same entry point as the ``neterse`` console script."""
import sys

from .audit import main

sys.exit(main())
