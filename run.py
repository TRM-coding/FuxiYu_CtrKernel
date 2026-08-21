import os
import sys
from importlib import import_module

import uvicorn

pkg_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(pkg_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from FuxiYu_CtrKernel.config import AppConfig

package_name = os.path.basename(pkg_dir)
create_app = import_module(package_name).create_app

app = create_app()

if __name__ == "__main__":
    ssl_enabled = getattr(AppConfig, "SSL_ENABLED", False)

    ssl_kwargs = {}
    if ssl_enabled:
        from FuxiYu_CtrKernel.utils.cert_utils import ensure_ctrl_certificates

        certs = ensure_ctrl_certificates()
        ssl_kwargs = {"ssl_certfile": str(certs.cert_file), "ssl_keyfile": str(certs.key_file)}

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("CTRL_PORT", "5000")),
        reload=False,
        **ssl_kwargs,
    )
