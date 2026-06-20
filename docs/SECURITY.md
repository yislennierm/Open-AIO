# Security

## Threat Model

- Malicious or compromised server response.
- Asset size abuse that exhausts ESP32 memory or flash.
- Path traversal against the asset endpoint.
- Privacy leakage from active window titles.
- LAN attacker calling APIs or serving spoofed responses.
- ESP32 crash from malformed JSON or unexpected asset metadata.

## Mitigations

- All API endpoints require `X-API-Key`.
- The PC agent sends process basename only and does not send window titles.
- The server normalizes `active_process` to lowercase basename.
- Process names map through a strict hardcoded app ID table.
- Unknown processes use the safe default app.
- Asset serving uses known app IDs and fixed manifest filenames.
- Arbitrary filesystem paths are not accepted.
- Server and firmware enforce maximum asset sizes.
- ESP32 verifies SHA-256 before replacing a cached logo.
- Firmware validates JSON fields and dimensions before rendering.
- Bad JSON, failed downloads, and hash mismatches keep the previous display state.

## MVP Boundary

This project is designed for local-only MVP use. The default API key must be changed. For use outside localhost or a trusted LAN, add HTTPS, stronger device credentials, key rotation, replay protection, and firewall rules.

