# CircuitPython libraries

This folder is ready to transfer to the root of the Pico's CIRCUITPY drive.

- Library: Adafruit CircuitPython HTTPServer
- Version: 4.8.2
- Build: CircuitPython 10.x compiled `.mpy` files (not desktop Python bytecode)
- Package directory: `adafruit_httpserver/`
- License: MIT; see `adafruit_httpserver/LICENSE`
- Official release: https://github.com/adafruit/Adafruit_CircuitPython_HTTPServer/releases/tag/4.8.2
- Archive: `adafruit-circuitpython-httpserver-10.x-mpy-4.8.2.zip`
- Archive SHA-256: `355e8daa0f0e96353d83b443bc830e5059d6b0944d05bcb16d702fce58d5b09e`

The 12 compiled modules are unchanged from the official release archive. This
library uses CircuitPython built-in modules and needs no additional libraries for
our Wi-Fi API. Adafruit Blinka is a desktop dependency, not a Pico installation
requirement. Examples from the archive are not included.

For a different CircuitPython major version, obtain the corresponding library
build rather than mixing incompatible `.mpy` files. Desktop tests install the
same library version from `requirements-test.txt` instead of importing these files.
