import http.server
import os
import sys
from pathlib import Path

_RANKING_DIR = Path(__file__).parent
_RANKING_ASSETS = _RANKING_DIR.parent / "assets" / "ranking"

os.chdir(str(_RANKING_ASSETS))
print(f"Serving on http://localhost:8765")
http.server.HTTPServer(("", 8765), http.server.SimpleHTTPRequestHandler).serve_forever()
