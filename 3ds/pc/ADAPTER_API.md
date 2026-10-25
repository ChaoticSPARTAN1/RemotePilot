# Adapter API and preset contract

## Homebrew companion extension (homebrew-v1)

The 3DS Homebrew section uses the `homebrew` python-v1 preset and a separate
`homebrew_request(action, object)` method. `PluginRuntime` validates the action's
manifest capability before invoking it; the adapter additionally requires the
authenticated companion to advertise the device capability. The ordinary game
request/action and button parsers are unchanged; `HOME` remains invalid game input.

| Viewer route | Body / response |
| --- | --- |
| `GET /api/homebrew/status` | Cached connection, capabilities, armed state, private job receipts, SD title inventory, system-input lease, launch handoff. No pairing token. |
| `POST /api/homebrew/configure` | `{host: "<private-ipv4>", port: 38765}` generates or retains independent private pairing; returns only pairing filename. Copy that file manually to the companion's SD directory after identifying the card. |
| `POST /api/homebrew/file` | CIA byte stream, `Content-Type: application/octet-stream`, `X-File-Sha256`, `X-Title-Id`, `X-Install: 0 or 1`; 512 MiB limit, hash/metadata checks before relay. `upload` capability required; install additionally requires `install`. Returns job ID, not installation success. |
| `POST /api/homebrew/download` | `{url, sha256, titleId, install: boolean}` downloads a final HTTPS URL on the PC, then verifies and relays. Redirects disabled; never store the URL in public job/status fields. |
| `POST /api/homebrew/titles` | `{}` refreshes installed SD base applications. |
| `POST /api/homebrew/cancel`, `/inspect` | `{id: "<32-hex-job-id>"}` request cancellation or read exact console outcome. Unknown AM outcomes require inspection; there is no automatic retry. |
| `POST /api/homebrew/launch` | `{titleId, preset: "morrowind" or "halo" or ""}` validates installed SD title and APT preparation; switches to the chosen existing paired transport after acknowledgement. Status distinguishes launching/game-connected/unavailable. |
| `POST /api/homebrew/system-arm` | `{enabled, owner: "<32-hex-tab-id>", version, inputRedirectionEnabled: true}` requires selected Homebrew preset, link enabled, manual Luma enablement and a focused-tab lease. |
| `POST /api/homebrew/system-input` | `{owner, button: "UP", milliseconds: 100}`, `{owner, home: true}`, or `{owner, touch: [x,y]}`; 20–250 ms, followed by neutral release. |
| `POST /api/homebrew/system-release` | `{}` attempts neutral packets and clears lease. |

All POSTs retain `X-Remote-Pilot-Viewer: 1`, origin and existing viewer cookie
checks. Homebrew JSON requests are limited to 4 KiB; game request limits remain
unchanged. The companion stays discoverable from this section when another game
preset is selected, but system input can only arm while Homebrew is selected.
Transfers/install polling run on a single bounded job worker; socket actions and
AM installation are never silently retried on timeout.
Verification and installation waits measure inactivity: authenticated native
phase or byte advancement renews the wait, so a large hash can finish beyond
three minutes. Repeated unchanged status and waiting for A do not renew it.
Every wait also has a four-hour ceiling; expiry requires inspection and never
resends an install command.

Luma UDP is unauthenticated and cannot acknowledge delivery or release. No status
claims HOME is visible, or that DS mode/video/audio are supported. See the sibling
RemotePilot-Homebrew project's protocol, licensing and pending hardware checklist.

The viewer is game neutral. Presets supply the name, artwork, colors, and
capability flags. Device transports own wire protocol, pairing, and capture
conversion. A third party should be able to add a game without putting its
name, console brand, or art in the shared viewer files.

## Preset manifest

Each `presets/<id>/manifest.json` contains:

| Field | Use |
| --- | --- |
| `id`, `name`, `order`, `mark` | Stable selector ID, visible name, order, short badge. |
| `transport` | Transport implementation key. The legacy receiver uses `legacy-reverse-v1`; adapter presets use `python-v1`. |
| `models` | Supported shell choices: `original`, `new-xl`. |
| `capabilities` | Viewer modules such as `screenshot`, `stream`, `audio`, `controller`, `console`, `input`, `report`, `log`, `perf`, `catalog`, `preview`. |
| `theme` | Nine six-digit hex colors: `background`, `surface`, `surface2`, `line`, `text`, `muted`, `accent`, `accent2`, `glow`. |
| `style`, `styleSheet` | Optional preset-only visual rules. The current heritage preset uses a local stylesheet and private trim images. |
| `analogInput`, `inputButtons`, `controllerOriginalFull`, `remoteReport`, `remoteLog` | Optional manual control, controller model mapping, and request availability. |

The receiver validates IDs and theme values before exposing manifests. A
stylesheet must remain inside its preset directory and never load external
URLs. Game names belong in manifests, catalogs, tests, and transport adapters.
The shared `viewer.html`, `viewer.js`, `viewer.css`, and `themes.css` should
remain independent of a particular game or device brand.

An optional `catalog.json` can describe maps, modes, and preview classes. It
contains metadata only; a preset with `preview` can ask the game to display
one of its installed assets and return a fresh screen capture. Owner assets
stay on the device.

## Add a local transport without editing the viewer

Set `transport` to `python-v1` and place an `adapter.py` beside the preset's
`manifest.json`. The receiver loads only that exact file from a validated
preset directory. The adapter is executable Python, so install only code you
trust. It may import sibling helper modules with relative imports. Its factory
receives a private `local/<preset-id>/` folder and the validated manifest:

```python
def create_adapter(local_dir, manifest):
    return MyAdapter(local_dir, manifest)

class MyAdapter:
    def status(self):
        # Called by a one-second background poll, never by an HTTP worker.
        return {
            "connected": False, "session": False, "host": "",
            "discovery": "waiting for paired device", "meta": None, "perf": None,
        }

    def request(self, kind, payload):
        # A bounded worker calls this after the receiver checks the selected
        # preset, live session, link switch, and capability flag.
        raise NotImplementedError
```

`start()` and `stop()` are optional lifecycle methods. `set_network_host(host)`
and `set_active(callback)` can optionally receive the PC LAN address and a
callback indicating whether the preset is selected. `status()` must report
cached state promptly. `connected` and `session` are booleans; `host` and
`discovery` are short strings; `meta` and `perf` are optional JSON objects.
The viewer keeps shared panels visible across presets and disables unsupported
device actions. `perf` uses finite nonnegative `fps`, `frameMs`, `workMs` and
an advancing `timestampMs`; device timing is separate from preview delivery FPS.
The combined metadata and performance JSON may not exceed 8 KB. Keep pairing
tokens and other secrets out of these fields. A failing adapter is shown as
disconnected and leaves the viewer running.

`request(kind, payload)` supports `console`, `input`, `gamepad`, `shot`, `stream`,
`report`, `log`, `perf`, and optional `preview`. Console payloads are printable commands up to
127 characters; input uses `<hex button mask> <frames> <moveX> <moveY>
<lookX> <lookY>`. Other requests use `-`. Return a text result of at most
4 KB for console, input, and perf. Return UTF-8 text of at most 64 KB for
report and log; the receiver saves it privately and records the filename.
For `shot` and `preview` return an uncompressed 400×480 24-bit BMP. For `stream`, return
an uncompressed 200×240 24-bit BMP, with the top screen above the lower. An
adapter with the `audio` capability may return `(bmp, pcm)` for `stream`, where
`pcm` is at most 16 KB of mono signed 16-bit little-endian audio sampled at
16,364 Hz. Audio is optional on each frame and is not stored with captures.
The receiver validates these images and saves full captures outside Git.
`preview` receives a selection such as `map:bloodgulch` or
`weapon:pistol:bloodgulch`. The adapter must validate it against its own
catalog and refuse unavailable device states; it should display the selected
asset before capturing. A selection must never start gameplay implicitly.
For `gamepad`, the receiver sends a complete standard controller snapshot in
the form `buttons=0001,lx=250,ly=-500,rx=0,ry=0,lt=0,rt=700,frames=8`.
The button mask uses browser Gamepad API bits 0 through 15; stick values are
signed thousandths and triggers range from 0 to 1000. New snapshots replace
older pending ones. The receiver drops stale snapshots before dispatch, and
the device adapter must release remote input after a short timeout, even if
the browser closes or the network breaks. The receiver does not retry a
timed-out gameplay action. Adapters own device authentication, address
discovery, transport framing, timeouts, and safe short input holds.
`python-v1` supports controller input only when its manifest declares
`controller`, and live audio only when it declares `audio`.

## Local HTTP viewer API

All JSON-changing calls use `POST` with `Content-Type: application/json` and
`X-Remote-Pilot-Viewer: 1`. The viewer is bound to `127.0.0.1` by default;
LAN mode uses a short pairing code and a secure cookie.

| Endpoint | Request or result |
| --- | --- |
| `GET /api/state` | Selected preset, connection/session state, queue, capture versions, optional device metadata and performance. |
| `GET /api/presets` | Ordered validated manifests and selected ID. |
| `POST /api/preset` | `{ "id": "preset-id" }`; persists local selection. |
| `POST /api/theme` | `{ "id": "preset-id", "colors": { "accent": "#3388cc" } }`; an empty object resets overrides. |
| `GET /api/catalog` | Selected preset's optional metadata. |
| `POST /api/link` | `{ "connected": true | false }`; PC-side command gate. |
| `POST /api/shot`, `POST /api/stream` | Request full capture or disposable preview. |
| `POST /api/capture` | Shared screen + optional existing-log bundle for any preset; returns `{capture, id, tasks}`. Reuses a pending bundle. |
| `GET /captures/<filename>` | Download a saved BMP, log TXT or capture JSON manifest through the authenticated viewer. |
| `POST /api/preview` | With a capable preset, `{ "kind": "map", "id": "bloodgulch" }` or `{ "kind": "weapon", "id": "pistol", "map": "bloodgulch" }`; opens the game's installed 3D preview and saves a full capture. |
| `POST /api/console`, `POST /api/input`, `POST /api/gamepad` | Bounded control requests; availability is transport dependent. |
| `POST /api/touch` | `{x: 0..319, y: 0..239, down: boolean}`; coalesced real bottom-LCD touch, shared by both game adapters. |
| `POST /api/report`, `POST /api/log`, `POST /api/perf` | Optional device diagnostics. |
| `GET /latest.bmp`, `GET /live.bmp` | Stacked top and bottom screen captures. |

Capture and report bodies are limited before parsing, written to ignored
`local/captures/`, and never included in `/api/state`. Display only from the
active preset so changing games cannot reveal the prior game's screen as a
current one.

`capture_api.py` atomically reserves screenshot and optional diagnostic tasks,
associates received files by task ID, and writes `capture-N.json`. `/api/state`
includes the selected preset's bundle IDs, task status and artifact filenames,
never file bodies. Presets advertise `remoteLog` / `remoteReport`; absent or
empty log results leave a successful screenshot with no invented log file.
Plugin collection is sequential. Legacy Morrowind queues a bounded `report`
action for its existing log tails, with a result acknowledgement followed by
the report file. File actions remain sent until their artifact arrives.

`touch_api.py` validates the shared LCD coordinates and encodes
`x=123,y=90,down=1`. Plugin request kind is `touch`; both device protocols use
that same payload. A release uses down=0. Refresh held samples at up to 10 Hz;
devices expire them at 900 ms and preserve physical-input priority. The Example
preset blocks all device actions and skips device discovery.

## Device transport responsibilities

The homebrew status snapshot includes `applicationTitleId`, `buildVersion` and
`updater` for the paired main companion/recovery updater. The **Wireless companion
updates** panel uses the existing raw upload route with fixed expected IDs and
`X-Install: 1`, followed by explicit launch calls without a game preset. The main
title (000400000f3d5200) never updates itself while running; updater
000400000f3d5300 can install only a higher version of that main title. Existing
bootstrap status without identity is accepted as main only. Both reuse the
companion pairing file and start disarmed. Approval is manual by default; optional
autonomous session permission is described below.
APT preparation is not proof that the target connected; the authenticated target
identity is checked after the jump. Unknown install/launch outcomes never retry.

`POST /api/homebrew/update` with `{ "kind": "updater" | "companion" }` uses the
same viewer origin/header/link gates and requires both upload and install
capabilities. Only the two fixed sibling build files matching their verification
receipt are accepted; HTTP requests cannot choose local paths. The ordinary
verified receive/spool/deploy path rechecks exact bytes. `localUpdates` in the
snapshot reports available version/title/size/hash metadata without paths or keys.
Deployments are blocked while a previous outcome is unknown or interrupted.
Main v6 / updater v5 report `autonomousSupported` and `autonomousEnabled`.
X arms and Y enables the optional mode on the console while idle; no HTTP action
enables it. New install jobs capture that mode and append `autonomous` to the
authenticated native begin request only when both flags are true. Job records
report `approvalMode`; manual and legacy jobs never become autonomous retroactively.
Existing file/download/update API calls can therefore be orchestrated by a paired
PC or AI without per-job A after session opt-in. Rehashing, title/version/storage,
AM completion and installed metadata checks remain mandatory. Y/disarm/restart/
fifteen idle minutes revoke permission. Revocation before AM writes falls back
to A approval. Unknown outcomes still block new deployments and never auto-retry.
Pairing address changes return `existingPairing: true` when the key is retained;
the UI then correctly says no SD config refresh is needed.

An adapter must implement authentication with a private pairing token,
bounded request and response lengths, a heartbeat, connection metadata,
screen capture, and safe failure behavior. It should make each request
idempotent or identify it with a request ID; a timeout must not silently
retry a gameplay action. Input should have a short finite hold time and
leave physical controls usable. Captures should be converted to a stacked
24-bit BMP with the top screen above the lower one; the viewer currently
expects 400×480 for a full capture and 200×240 for preview.

The RP1 client interface in `halo_adapter.py` is a concrete example:

```python
adapter = HaloAdapter(device_ipv4, port, token_hex)
adapter.heartbeat()
metadata = adapter.meta()
sample = adapter.perf()
image = adapter.shot_bmp()
preview = adapter.stream_bmp()
result = adapter.input(keys=0x10, frames=4)
```

The legacy transport uses its own challenge, session, input axes, optional
audio preview, and Bug It upload route. Its protocol is intentionally kept
separate from RP1. New device protocols should use a new transport key and
adapter module; they should not inherit either game's wire identity or token.
Updated Morrowind builds send `MW3DS1 perf 0 <bytes>` followed by at most
1,024 bytes of JSON: `fps`, `frameMs`, `workMs`, `cpuMs`, `gpuMs`,
`linearFreeKb`, `heapUsedKb`, `timestampMs`. This is an authenticated,
persistent-socket response and writes no capture file. The shared state route
exposes the latest valid sample only while contact and timing are fresh.
The viewer requests legacy telemetry through coalesced `POST /api/perf`
at at most 1 Hz. Its authenticated `0 perf -` action opts the device in for
five seconds. Older receivers never request it, so their wire behavior remains
compatible; older devices ignore the optional action and keep their link alive.

The legacy device wire protocol and the RP1 preset retain separate
implementations. Additional transports register through `python-v1` without
modifying the shared viewer or receiver routing. An adapter may provide
`configure(device_host, port)` for the generic `setup-preset <id>` command;
its documentation should state where to copy the returned private SD file.
