# Remote Pilot

Remote Pilot is a local browser viewer for homebrew device testing. Currently setup for 3d/duel screen family of devices but can be extended to other devices in the future. An optional
device preset supplies the transport and declares the features its build
supports. The checked-in **Example** preset is an offline preview. This source
contains no game data, device media, pairing keys, saved captures, or personal
network configuration.

## Start

For CIA transfers, wireless companion updates and the original 3DS dashboards,
use the separate **[3DS tool bundle](3ds/README.md)**. It includes the PC tool,
main/Recovery CIA and 3DSX builds, matching source, artwork, setup instructions
and security/legal review. All platform-specific additions live under `3ds/`.

The 3DS native companion is GPL-3.0-only; the independent PC code remains MIT.

For the PSP, use the **[PSP section](psp/README.md)**: the RemotePilot PSP
companion (a guided on-console app: settings backup and restore, Wi-Fi check,
live view and remote control), its PC viewer section and the **PSP · Homebrew**
preset, a template for any PSP build that answers RemotePilot's RP2 protocol.
It lives under `psp/` and is MIT, apart from the third-party pieces in
[psp/NOTICE.md](psp/NOTICE.md).
The current 0.8.0 release is a preview pending fresh hardware validation.

Install Python 3.11 or newer. On Windows, open `run.cmd`; on macOS or Linux, run
`sh run.sh`. The launcher opens the viewer at a free loopback address. No fixed
viewer port, cloud account, or inbound PC firewall rule is required. To avoid
opening a browser automatically, run `python server.py --no-browser` and open
the printed local URL yourself.

The first-run guide appears in the viewer. Example needs no device and makes no
network connection. Once a trusted device preset is installed, select it and:

1. Choose **Prepare pairing**. The adapter generates a random token and a
   private config for the device. The token is reused when setup is repeated.
2. Choose **Copy to selected device folder** and select the storage root. The
   viewer creates the documented relative path. If your browser does not offer
   directory access, choose **Download device config** and copy it to that path.
3. Start the matching homebrew build and enable its PC link. The reference
   adapter searches the current private local network and connects once the
   device proves it knows the token. **Retry connection** starts a fresh scan.
   If automatic search misses a device, enter the private device IPv4 address
   in the setup guide and choose **Use address**. The viewer saves that choice
   only in ignored local pairing data; **Search automatically** clears it.

The integrated build must implement the [RP2 protocol](docs/PROTOCOL.md), or
provide its own trusted Python adapter. A browser cannot add support to a
device build that has no integration. Developers can create a starter preset
with `python tools/new_preset.py --help`; see the
[integration guide](docs/INTEGRATION.md) and [example implementation prompt](docs/EXAMPLE_PROMPT.md).

## Use

- **Grab full capture** saves a device image and, if selected and supported, a
  log or report under ignored `local/captures/`.
- **Live preview** requests bounded frames at the chosen maximum rate. **Sound**
  is opt in and plays mono PCM supplied with those frames.
- **Enable mouse and controller input** lets a focused viewer send standard
  controller snapshots. Drag the virtual sticks; use preset buttons for short
  presses. The device should expire remote input if packets stop.
- If the preset declares controller button bits, hold Ctrl and click multiple
  buttons, then release Ctrl for one short simultaneous press.
- A declared touch region maps clicks and drags to device coordinates.
- Console commands, timing, reports, logs, catalogs, and safe menu previews
  appear only when the preset advertises them.
- **Pause PC link** stops host actions. The device's own session switch must
  also allow remote access.
- **Device view** starts with a New 3D 2 Screen shell for stacked dual-screen
  presets, including a circle pad, C stick, and ZL/ZR indicators. Switch to
  **Original 3D 2 Screen** to hide the second stick and ZL/ZR, or **Generic frame** to
  inspect the uncropped image. The offline Example preset shows these layouts
  and previews lower-screen touch coordinates without contacting a device.
- **Preset colors** lets you save separate background, surface, accent, and
  text colors for each preset. The performance graph follows that theme.

The console and raw frame views use a themed waiting screen until the selected
build supplies a capture or live frame. They contain no bundled game image;
new frames replace the waiting screen in the local viewer as they arrive.

The viewer listens only on this computer. Preset adapters are executable Python
loaded from `presets/<id>/adapter.py`; install only adapters you trust. The
checked-in bundle includes no live adapter. `local/` is ignored by Git and
keeps pairing files, captures, themes, request history, and cached addresses on
this computer. See [security notes](docs/SECURITY.md).

## Portable bundle and license

Run `python build_portable.py` to create `dist/RemotePilot-portable.zip`. Its
explicit file list includes only the Example preset and source needed to run
and integrate the viewer. The archive includes a checksum manifest; it never
includes `local/` or other unlisted files.

Remote Pilot's original source is licensed under [MIT](LICENSE), copyright
2026 Kevin Boggs. Integrations must keep their own third-party notices and
obtain permission for any media they distribute.

Remote Pilot is an independent project, not affiliated with, endorsed by or
sponsored by Nintendo, Sony Interactive Entertainment, Microsoft, Halo Studios
or Bungie. Nintendo 3DS, PSP and PlayStation, and Halo are their owners'
trademarks, named only to say what the tools work with.

### Performance capture

The Performance capture checkbox is available in every preset and both device layouts. It defaults to off and remembers the choice per preset. Turning it off stops automatic timing requests and clears the graph; connection checks, Bug It, screenshots, and live preview remain available. A timing request already in flight may finish.
