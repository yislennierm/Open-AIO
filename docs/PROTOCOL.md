# Protocol

All API requests require:

```http
X-API-Key: change-me
```

## Telemetry POST

```http
POST /api/v1/device/{device_id}/telemetry
Content-Type: application/json
```

Request:

```json
{
  "active_process": "steam.exe",
  "cpu_temp": 58.5,
  "gpu_temp": 64.0,
  "cpu_load": 32.0,
  "gpu_load": 48.0,
  "ram_used_percent": 71.0
}
```

Nullable fields:

- `cpu_temp`
- `gpu_temp`
- `gpu_load`

Response:

```json
{
  "ok": true,
  "device_id": "cooler-display-01",
  "app_id": "steam"
}
```

## State GET

```http
GET /api/v1/device/{device_id}/state
```

Response:

```json
{
  "device_id": "cooler-display-01",
  "app_id": "steam",
  "display_name": "Steam",
  "asset_type": "rgb565",
  "asset_url": "/assets/apps/steam/logo_160x160.rgb565",
  "asset_hash": "sha256_hex_here",
  "asset_width": 160,
  "asset_height": 160,
  "cpu_temp": 58.5,
  "gpu_temp": 64.0,
  "cpu_load": 32.0,
  "gpu_load": 48.0,
  "ram_used_percent": 71.0,
  "updated_at": "2026-06-07T18:00:00Z"
}
```

## Asset GET

```http
GET /assets/apps/{app_id}/{asset_file}
```

Only known app IDs are accepted. Missing app assets fall back to the default app asset.

## SignalRGB LCD Stream

SignalRGB sends LCD frames to the ESP32 over either USB CDC serial or RawUSB bulk OUT. This transport is separate from the FastAPI telemetry API above.

All SignalRGB LCD packets use a 20-byte little-endian header:

| Offset | Size | Field |
| --- | ---: | --- |
| 0 | 4 | Magic: `SRGB` |
| 4 | 1 | Command |
| 5 | 1 | Scale or command-specific value |
| 6 | 2 | Payload checksum, unsigned sum of payload bytes |
| 8 | 2 | X coordinate for rectangle commands |
| 10 | 2 | Y coordinate for rectangle commands |
| 12 | 2 | Width for rectangle commands |
| 14 | 2 | Height for rectangle commands |
| 16 | 4 | Payload length |

Commands:

| Command | Name | Payload |
| ---: | --- | --- |
| `0x01` | RGB565 rectangle | `width * height * 2` bytes at fixed scale 2 |
| `0x02` | Flush | No payload; presents the pending rectangle frame |
| `0x03` | Scaled RGB565 rectangle | `width * height * 2` bytes; header byte 5 is the scale |
| `0x04` | Local FX | 8 bytes: base RGB, accent RGB, energy, reserved |
| `0x05` | JPEG frame | JPEG bytes for the full 480x480 LCD preview |

RawUSB status packets are optional device-to-host replies on the bulk IN endpoint. The plugin only polls these when `Log Device Status` is enabled.

Status packet format:

| Offset | Size | Field |
| --- | ---: | --- |
| 0 | 4 | Magic: `SRSP` |
| 4 | 1 | Status code |
| 5 | 1 | Command that produced the status |
| 6 | 2 | Detail, usually payload length or checksum |
| 8 | 4 | Device `millis()` timestamp |

Status codes:

| Code | Name |
| ---: | --- |
| `0x00` | OK |
| `0x01` | BAD_MAGIC |
| `0x02` | BAD_COMMAND |
| `0x03` | BAD_LENGTH |
| `0x04` | BAD_CHECKSUM |
| `0x05` | RENDER_FAILED |
