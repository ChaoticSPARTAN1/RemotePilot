# RP2 device protocol

RP2 is the optional reference transport for a homebrew build. It uses a single
TCP request per connection on the device's private LAN address. The PC opens the
connection; the device never needs a PC address, PC listener, cloud service, or
router forwarding. `reference_transport.py` is the host implementation. A game
may instead ship a trusted adapter for a different protocol.

## Pairing and session

The viewer's **Prepare pairing** action writes a private host pairing file and
a device config containing:

```text
app_id=<preset-id>
port=<random available high port>
token=<64 lowercase hexadecimal characters>
session=on
```

Treat the 32-byte token as a secret. Keep it out of source, logs, screenshots,
diagnostics, and bug reports. Read it from the device config at launch. Do not
start the listener when `session=off`. Provide an in-game way to turn the
session off and show whether the PC is connected. The setup UI offers a storage
folder picker and a download fallback; the game's preset declares the relative
destination path. No personal address or port is part of the preset.

Listen only on a local private interface and the configured port. Reject
connections from outside the local private network. Bound simultaneous clients,
all lines, bodies, and time spent per request. Close each connection after one
response. A successful HMAC exchange is required before any action.

## One exchange

All lines end in `\n` and contain printable ASCII. Body bytes follow a header
immediately; no extra delimiter follows a body. The device generates a fresh
16-byte nonce per connection. Integers are unsigned decimal with no sign.

1. Host: `RP2 HELLO <app_id>\n`. Reject a mismatched application ID.
2. Device: `RP2 CHALLENGE <nonce_hex> <proof_hex>\n`, where
   `proof = HMAC-SHA256(token, b"device\n" + app_id + b"\n" + nonce)`.
3. Host verifies that proof in constant time. It chooses a random request ID
   and sends `RP2 REQUEST <id> <kind> <length> <mac_hex>\n<body>`, where
   `mac = HMAC-SHA256(token, b"request\n" + nonce + b"\n" + id + b"\n" + kind + b"\n" + body)`.
4. Device verifies the request MAC in constant time, performs one bounded
   action, and sends `RP2 RESPONSE <id> <kind> <length> <mac_hex>\n<body>`, where
   `mac = HMAC-SHA256(token, b"response\n" + nonce + b"\n" + id + b"\n" + kind + b"\n" + body)`.
5. For a rejected action, return the signed response kind `error` and a short
   generic message. Reuse the request ID. The host validates response ID,
   kind, size, and MAC before exposing the body to the viewer.

The domain strings `device`, `request`, and `response` keep the three proofs
distinct. Use a platform SHA-256/HMAC implementation; never write a new crypto
primitive. This authenticates local messages but does not encrypt them. Keep
the device on a trusted private network and do not forward its port to the
internet. Rotate pairing by removing the local pairing file, rerunning setup,
and replacing the device config.

Request bodies are at most 8 KiB. Image responses are at most 4 MiB; report and
log responses at most 64 KiB; metadata at most 8 KiB. The reference adapter
applies shorter timeouts for ordinary actions and longer ones for images.

## Actions

The response kind matches the request kind unless the device returns `error`.
Unavailable capabilities should fail explicitly. Metadata and timings are
UTF-8 JSON; report and log text are UTF-8. Keep secrets and raw network state
out of every response.

| Kind | Request body | Response body |
| --- | --- | --- |
| `ping` | Empty | Empty; proves the device is paired. |
| `meta` | Empty | JSON with `schemaVersion: 2`, matching `appId`, and optional `label`, `state`, `captureSequence`. |
| `perf` | Empty | JSON with finite nonnegative `fps`, `frameMs`, `workMs`, and advancing `timestampMs`. |
| `shot` | Empty | Full PNG or uncompressed 24/32-bit BMP. |
| `stream` | Empty | Live packet described below. |
| `report`, `log` | Empty | Bounded diagnostic text, with secrets removed. |
| `console` | Printable command, at most 127 characters | Short text result. Allow only commands safe for remote QA. |
| `input` | JSON `{"button":"PRIMARY","frames":1}` | Short text acknowledgment. Honor the preset's declared button list. |
| `gamepad` | JSON standard controller snapshot | Short text acknowledgment. |
| `touch` | JSON `{"x":0,"y":0,"down":true}` | Short text acknowledgment. |
| `preview` | Catalog item ID, at most 128 safe characters | Image of the selected item in a menu. Do not start play. |

For `gamepad`, send `buttons` as a 16-bit standard Gamepad API mask, axes
`lx`,`ly`,`rx`,`ry` in `[-1,1]`, triggers `lt`,`rt` in `[0,1]`, and `frames`
from 1 to 8. Coalesce superseded snapshots. The device must clear remote input
after a short timeout, including when the browser closes. Physical input should
take priority. `input` is limited to 30 frames. For `touch`, the preset defines
the pixel region and the device coordinate range; the device must release on a
`down:false` sample or timeout.

The live response starts with two unsigned little-endian 32-bit lengths:
`image_length`, `audio_length`, followed by image bytes and optional audio
bytes. The image is a PNG or uncompressed BMP with the preset display aspect
ratio. Audio is at most 16 KiB of mono signed 16-bit little-endian PCM, at the
sample rate declared in the preset. Zero audio length is valid. Live preview
is off by default; sound requires a separate user action.

If the device has a local bug-report action, increment `captureSequence` in
`meta` after the user triggers it. The host observes new values while connected
and saves a full capture plus report (or log). On initial connection, the
current value becomes the baseline so old events are not replayed.

## Device implementation checklist

1. Add an opt-in listener lifecycle to the game and load the private config.
2. Parse and authenticate RP2 with fixed buffer limits and constant-time MAC
   comparison. Keep all socket work off the render thread.
3. Implement `ping`, `meta`, and `shot` first. Verify connection and capture.
4. Add stream/audio, timing, diagnostics, console, input, touch, and catalog
   preview one capability at a time. Declare only features that actually work.
5. Bound image copying per frame, prioritize local controls, and expire remote
   holds. Check for frame hitches on physical hardware.
6. Test wrong-token, replayed-action, oversized-message, disconnect, network
   change, and session-off behavior before distributing an integration.
