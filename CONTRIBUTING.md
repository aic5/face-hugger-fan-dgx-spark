# Contributing

Contributions that make the build safer, easier to reproduce, or better measured
are welcome.

## Before opening a change

- Do not include Wi-Fi credentials, dashboard passwords, IP addresses tied to a
  private network, session cookies, or other secrets.
- Separate measured results from estimates and clearly state the test conditions.
- Link primary manufacturer documentation for electrical claims.
- Preserve the full-speed fail-safe unless a change includes a documented safety
  analysis and tests.
- Keep 12 V isolated from Pico power and GPIO paths in every wiring example.

## Software checks

Run the desktop test suite from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -v
```

The tests simulate hardware. They do not validate an electrical assembly, Wi-Fi
reliability, fan airflow, or DGX thermal behavior.

## Reporting a hardware result

Include the fan model, converter model, power source, wiring revision, fan
position, printed-part revision, CircuitPython version, commit hash, ambient
temperature, DGX power mode, workload, sample interval, and raw data when possible.

By contributing, you agree that your contribution may be distributed under this
repository's MIT License. Bundled third-party files remain under their own terms.
