# Security

## Supported Versions

The public release is experimental. Security fixes target the default branch.

## Reporting

Open a GitHub security advisory or a private issue if you find a vulnerability.
Do not publish exploit details before maintainers have had time to respond.

## Local Network Boundary

The daemon is intended for a trusted local network. It has no authentication and
should not be exposed to the public internet.

## Sensitive Data

The public repo must not include:

- Device serial numbers.
- Personal paths or LAN IP addresses.
- Account tokens, API keys, cookies, or AI quota cache files.
- Jailbreak exploit payloads or hotfix artifacts.

If any sensitive data is found in the repo, treat it as a release blocker.
