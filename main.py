#!/usr/bin/env python3
"""PWRcell v3 Entry Point.

Run the companion Web Explorer:
    python main.py explore [--mock] [--port 5555]

Or run directly without arguments to launch the explorer:
    python main.py --mock
"""

import sys
from pwrcell.cli import main

if __name__ == "__main__":
    main()
