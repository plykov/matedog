#!/usr/bin/env python3
"""Start MateDog and open it in the default browser."""

import os
import threading
import webbrowser

from matedog.server import main

if __name__ == "__main__":
    host = os.environ.get("MATEDOG_HOST", "127.0.0.1")
    port = os.environ.get("MATEDOG_PORT", "8123")
    if os.environ.get("MATEDOG_NO_BROWSER") != "1":
        threading.Timer(1.0, webbrowser.open, [f"http://{host}:{port}"]).start()
    main()
