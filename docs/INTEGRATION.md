# Integrate Remote Pilot with a homebrew build

The viewer is intentionally independent of a particular game or device. A
preset describes the display, available controls, and optional features. Its
adapter handles pairing, discovery, framing, and conversion to the viewer's
common formats. The checked-in Example preset is offline; the source bundle
ships no connected preset or device data.

## Fast path: the RP2 reference adapter

1. Add the [RP2 device handler](PROTOCOL.md) to your homebrew build. Begin with
   `ping`, `meta`, and `shot`, then add other actions as they become stable.
   Read the generated config from a path appropriate for your platform. Keep
   the listener disabled when the config or in-game session switch says off.
2. Create a preset on the PC. Replace the values below with your app's ID,
   display size, and relative config destination:

   ```text
   python tools/new_preset.py --id my-homebrew --name "My Homebrew" --width 640 --height 360 --device-config-path remote-pilot/device.cfg
   ```

   The starter advertises screenshots only. Add
   `--capabilities screenshot,stream,controller,input,report,log,perf` only for
   actions the device actually implements. Add
   `--touch x,y,width,height,deviceWidth,deviceHeight` for a working touch
   region and `--audio-rate <sample-rate>` if live frames include PCM. Use
   `--layout dual-screen` when the image is two equal-height screens stacked
   vertically, with a centered lower touch screen. The viewer starts with
   a New 3D 2 Screen shell; the user can select Original 3D 2 Screen or the raw
   composite frame. This shell is CSS and ships no hardware artwork. Use
   `--buttons` to specify names your build accepts for bounded digital input.
   A preset with `controller` can declare `buttonBits`, mapping button names
   to its 16-bit controller mask positions. Ctrl+click uses this mapping to
   send one simultaneous press when Ctrl is released.
   The script validates the manifest and creates `presets/<id>/manifest.json`
   plus a thin adapter. It generates **no token, device address, or port in
   source**.
3. Restart Remote Pilot. Select the new preset, click **Prepare pairing**, and
   choose **Copy to selected device folder**. Select the storage root, not the
   final subfolder; the viewer creates the declared path. Use **Download device
   config** if the browser lacks folder access. Start the matching build.
4. The PC searches only its current private local networks. If it has multiple
   interfaces or a segmented network, enter the device's current private IPv4
   in the setup guide and choose **Use address**. This changes only ignored
   local pairing data. **Search automatically** restores the default.
5. Exercise a short input, full capture, optional log/report, and live preview.
   Confirm the device remains playable while streaming and that closing the
   browser releases held input.

The host accepts only PNG or uncompressed BMP frames, up to 4 MiB, with the
same aspect ratio as the preset display. The app's output may combine multiple
screens into one image. A touch region in the manifest identifies the portion
of that image that accepts input; the viewer maps it to device coordinates.

## Alternative transport adapter

If your build already has a local authenticated protocol, put a trusted Python
`adapter.py` beside its `manifest.json`, set `transport` to `python-v1`, and
implement `create_adapter(local_dir, manifest)`. `local_dir` is an ignored
private folder for pairing and cache files. The returned object provides:

```python
class Adapter:
    def status(self):
        return {
            "connected": False,
            "session": False,
            "host": "",
            "discovery": "Waiting for paired device",
            "meta": None,
            "perf": None,
        }

    def request(self, kind, payload):
        raise NotImplementedError

    def setup(self):
        # Save a private device config inside local_dir.
        return {"configPath": str(local_dir / "device.cfg")}
```

`status()` is polled off the HTTP thread and must return cached data quickly.
`request()` is serialized per preset on a bounded worker. It receives `-` for
bodyless actions, a printable string for `console`/`preview`, and a JSON string
for `input`/`gamepad`/`touch`. It returns bytes for `shot` and `preview`, a
`(image_bytes, pcm_bytes)` tuple for `stream`, a short text result for controls,
and bounded UTF-8 text for `report`/`log`. `perf` may return a short text or
JSON object; live performance data should be cached in `status()["perf"]`.

Optional `start()`, `stop()`, `retry()`, and `set_active(callback)` lifecycle
methods are supported. `set_event_sink(callback)` can report a new on-device
capture event as `callback("capture", sequence)`; the receiver saves a full
image and available report/log. Never echo tokens in exceptions, `status()`,
or device diagnostics. The viewer exposes short, generic error types.

## Capability and safety rules

`manifest.json` declares a stable ID, visible name, display width/height,
button names, nine local theme colors, and only the capabilities actually
implemented. Supported flags are `screenshot`, `stream`, `audio`, `controller`,
`console`, `input`, `touch`, `report`, `log`, `perf`, `catalog`, and `preview`.
Audio requires stream and a declared sample rate. Touch requires a rectangle
and device coordinate dimensions. A catalog is optional local metadata:

```json
{"groups":[{"name":"Scenes","items":[{"id":"scene:first","label":"First scene"}]}]}
```

The preview action should only show a selected item in a safe menu and return
an image. Do not change gameplay state as a side effect of browsing a catalog.
Ship no proprietary or owner-extracted media in a preset. The viewer renders
plain metadata text and images received live from a paired device.

Use a short remote-input expiry on the device, keep physical controls usable,
and bound the time spent capturing screenshots. Keep remote commands disabled
until a locally armed session and authenticated peer exist. Use an allowlist
for console commands; avoid arbitrary file access or command execution.

## Distribution

Package your game's preset with your integration release and tell users where
to place it under `presets/<id>/`. The generic Remote Pilot bundle includes
only Example. Run its first-time flow on a clean machine with a fresh pairing
before shipping instructions. Keep token files, captured media, logs, device
addresses, and personal settings out of version control and release archives.
Respect the license and attribution rules of both this tool and your game.

## Check before sharing

Run `python -m unittest discover -s tests -v`, `node --check viewer.js`,
and `python build_portable.py`. Inspect `git diff --cached --name-status` and
`git diff --cached` before every push, plus `git log --all --stat` if the repo
has earlier commits. Open the ZIP and check its member list against the
explicit whitelist in `build_portable.py`. Search the staged source and prior
commits for tokens, credentials, private host addresses, user file paths,
device media, and captured output. Tests and scanners are aids to review;
they cannot certify an arbitrary third-party preset or game binary.
