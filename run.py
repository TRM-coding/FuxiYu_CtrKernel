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
	app.run(host="0.0.0.0", port=5000, debug=True)

