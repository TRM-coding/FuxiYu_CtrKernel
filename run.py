import os
import sys
from importlib import import_module

pkg_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(pkg_dir)
if parent_dir not in sys.path:
	sys.path.insert(0, parent_dir)

package_name = os.path.basename(pkg_dir)
try:
	create_app = import_module(package_name).create_app
except Exception:
	create_app = import_module('__init__').create_app

app = create_app()

if __name__ == "__main__":
	# Use SSL when configured (development only). If cert/key files exist, use them;
	# otherwise fall back to Flask's adhoc cert for quick local testing.
	ssl_enabled = app.config.get("SSL_ENABLED", False)
	if ssl_enabled:
		cert_path = app.config.get("SSL_CERT_PATH")
		key_path = app.config.get("SSL_KEY_PATH")
		if cert_path and key_path and os.path.exists(cert_path) and os.path.exists(key_path):
			ssl_ctx = (cert_path, key_path)
		else:
			# fallback to an auto-generated certificate (not for production)
			ssl_ctx = 'adhoc'
		app.run(host="0.0.0.0", port=5000, debug=True, ssl_context=ssl_ctx)
	else:
		app.run(host="0.0.0.0", port=5000, debug=True)

