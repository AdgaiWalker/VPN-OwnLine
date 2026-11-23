#!/usr/bin/env python3
"""Cross-platform entrypoint for the Evergreen OwnLine local engine."""

import sys

from server.ownline_cli import main


if __name__ == "__main__":
    sys.exit(main())
