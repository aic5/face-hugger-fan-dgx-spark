# Security

## Supported scope

This project is intended for a trusted local network. The Pico dashboard and API
use plain HTTP: credentials, cookies, telemetry, and commands are not encrypted
in transit. Do not expose the controller to the public internet, guest Wi-Fi, or
an untrusted LAN.

## Reporting a vulnerability

Please use GitHub's private vulnerability-reporting feature for the repository
instead of opening a public issue with exploit details. Do not include real
credentials, cookies, private IP inventories, or other users' data.

## Deployment guidance

- Use a long, unique dashboard password.
- Keep `settings.toml` and `/etc/dgx-fan-telemetry.env` out of Git.
- Restrict the network so only trusted devices can reach the Pico.
- Treat physical access to the CIRCUITPY drive as administrative access.
- Review updates before copying them to the controller.
- Remember that authentication and software fail-safes do not compensate for an
  unsafe electrical design or loss of controller power.
