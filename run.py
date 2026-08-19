import os
import sys
from importlib import import_module

import uvicorn

pkg_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(pkg_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

package_name = os.path.basename(pkg_dir)
try:
    create_app = import_module(package_name).create_app
except Exception:
    create_app = import_module("__init__").create_app

app = create_app()

if __name__ == "__main__":
    flask_app = app.state.flask_app
    ssl_enabled = flask_app.config.get("SSL_ENABLED", False)
    cert_path = flask_app.config.get("SSL_CERT_PATH")
    key_path = flask_app.config.get("SSL_KEY_PATH")

    ssl_kwargs = {}
    if ssl_enabled and cert_path and key_path and os.path.exists(cert_path) and os.path.exists(key_path):
        ssl_kwargs = {"ssl_certfile": cert_path, "ssl_keyfile": key_path}

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("CTRL_PORT", "5000")),
        reload=False,
        **ssl_kwargs,
    )
