# RemotePilot for PSP

The PSP section of RemotePilot. It is kept apart from the 3DS tools in [`3ds/`](../3ds/README.md), as they are kept apart from the generic viewer.

**Licence:** MIT, apart from the third-party pieces listed in
[NOTICE.md](NOTICE.md) (a CC0 hash, two fonts). **Not affiliated** with Sony
Interactive Entertainment, Microsoft, Halo Studios or Bungie: PSP and
PlayStation are Sony's trademarks, Halo is Microsoft's, used only to say what
the tools work with.

| Directory | Contents |
| --- | --- |
| `pc/` | The viewer with the PSP section: the **PSP · Homebrew (RemotePilot PSP)** preset (a template for any PSP build that answers RP2), a PSP-style device view and controls, live view, screen capture, device log, the **PSP folders** browser, the **PSP settings backup**, and **Options → Write a bug report** (saved on this computer only) |
| `device/` | The PSP side of RP2 in portable C (`rp2_device.c`: pairing, HMAC, one bounded request per connection; `rp2_actions.c`: the actions; `rp2_backup.c` and `rp2_restore.c`: the settings backup and restore), the companion's screens (`ui/`), the restore's kernel helper (`flash/`, `rp_flash.prx`), plus `platform_host.c`, a desktop simulator that runs the same code |
| `tools/` | `build_sim.py` builds the simulator, `build_psp.py` the EBOOT and its helper, `render_screens.py` draws the companion's screens on a PC |

## Status (2026-10-29)

- **Simulator: working.** The viewer and simulator were tested end to end.
  - Pairing, ping/meta, screenshot (480×272 BMP) and live stream (240×136 BMP packets, 5 in a row).
  - Device log tail, folder listings, whole-file copies (log, a 392 KB picture), and controller input.
  - Refusals: the pairing file is never listed or sent, and path traversal is rejected by both the viewer and the device.
  - Settings backup: made on the simulator's stand-in flash1, fetched by the viewer and checked file by file; a second backup gets its own folder; a corrupted copy is refused and nothing half-copied is kept; a device that can't read flash1 says so and writes nothing.
  - Settings restore: a reset is put back (only the files that differ, the registry last, each read back); nothing is written from a damaged backup, one from other firmware, or a manifest that points outside flash1.
  - 30 Python tests (21 of them against the simulator) and the Node tests pass.
- **On the PSP (PSP-1000, 6.61, ARK-4):**
  - **Run on hardware:** the first companion build. A user-mode EBOOT reads flash1, and the backup worked: 7 files, each copy checked.
  - **Built, not yet run on hardware:** the guided screens (`ui/`), the restore and its kernel helper, and the Wi-Fi check. They compile with psp-gcc 15.2.0, `-Wall -Wextra -Werror`, no warnings; `tools/render_screens.py` draws every screen on a PC from the same code.
  - Its screens: a home screen (with the check against the newest backup), **△ Back up**, **□ Restore**, **✕ Connect**, and from Connect, **△ Wi-Fi check**. The network starts only from Connect, with the WLAN switch on.
  - Still to see on hardware: the helper's writes to flash1, the socket timeout's unit (written as microseconds), and how long connection 1 takes to come up.
- **Inside a game** (live view and control during play, for example in Sierra-III's Halo CE port) is still to come. On a PSP-1000 (32 MB) the campaign build has no network modules and no spare memory for them. Sierra-III's multiplayer build does load them. This needs measuring on hardware before it's promised. A PSP-2000/3000 (64 MB) has room.

## Back up the PSP's system settings

The PSP keeps its settings in its own flash memory (flash1): date and time,
nickname, network connections with their Wi-Fi passwords, theme choices, and a
custom theme you installed (its own copy, kept even after the original `.ptf`
file is gone). A settings reset loses all of it. Back it up before testing
anything that could cause one, such as a sleep fix.

- **On the PSP, no PC or Wi-Fi needed:** start **RemotePilot PSP** and press
  **△ Back up**, then **✕**. It copies flash1 into a new folder,
  `ms0:/BACKUP/flash1-<date>-<time>`, reads each copy back to check it, and
  shows how many files it copied and whether your wallpaper and custom theme
  were among them. Each start of the app compares the settings with the
  newest backup and says whether they still match.
- **Over Wi-Fi, to this computer:** in the viewer's **PSP settings backup**
  panel, **Back up PSP settings** does the same on the PSP, then copies every
  file here and checks each against what the PSP read. **Copy a backup made on
  the PSP** fetches one made with TRIANGLE. Copies are kept in
  `pc/local/backups/<preset>/`; a copy that doesn't match is never kept.
- **From a card reader:** copy the `ms0:/BACKUP/flash1-…` folder off the card
  and check it with `python psp/pc/settings_backup.py <folder>`.

A backup only reads the settings memory. Keep backups private: they hold
your Wi-Fi passwords.

## Restore the settings (on the PSP only)

**□ Restore** on the companion's home screen, then:

1. **Pick** a backup (newest first) and press **✕**.
2. **Check:** the copies on the card must match their manifest, the backup must
   come from the same firmware (a backup from before firmware was recorded is
   allowed, and says so), and the screen lists what differs from now.
3. **Confirm:** hold **✕** for two seconds. Letting go starts the count again.
4. **Restore:** only the files that differ are written, the registry last, by
   `rp_flash.prx` (a small kernel module beside the EBOOT: a user-mode EBOOT
   can read flash1 but not write it). Each file is read back and compared.
5. **Restart:** the PSP restarts by itself straight away, before the system
   can write its settings from memory over the restored ones.

**Not yet run on hardware:** the restore and its kernel helper are tested on
the simulator only (a reset put back, a damaged backup, other firmware, paths
outside the settings folders). Until it has been run on a PSP, keep a copy of
your backup on a PC too; the custom firmware's USB flash1 mount is the other
way to copy the settings out.

Before writing anything, a restore backs up the settings as they are now, so
a restore that goes wrong can itself be undone; with no room for that backup
it writes nothing. Each file is written beside its old one, read back, then
put in its place.

Nothing on the network can start a restore: it has no RP2 action, and its
confirming hold takes the PSP's own ✕ only (remote buttons drive every other
screen).

**The kernel helper** (`rp_flash.prx`) trusts nothing in user memory while it
works: it takes the job's address only from the user partition, copies the job
once into its own memory and uses only that copy, reads each file into a
buffer of its own in kernel memory, and writes only into flash1's settings
folders (`registry`, `vsh/theme`, `dic`, `net/http`, `gps`, `updater`). Only flash1 is written, never flash0, and the helper
refuses any path but `flash1:/…` from `ms0:/BACKUP/flash1-…`. If a write
fails partway, the PSP may ask to reset its settings at the next start: let
it, and restore again from the same backup.

## Wi-Fi check

From **✕ Connect**, **△ Wi-Fi check** shows:

- the WLAN switch as the firmware reads it, live, with a strip of the last
  twelve seconds: slide it up and down, and flicker means worn or dirty contacts;
- whether the Wi-Fi chip answers (its address's first half only);
- whether connection 1 is set up, its network name and security type (never
  its key);
- a join test (**✕**): each step the firmware reports, with its time and error
  code, then the address, signal strength and channel;
- what that means, in a sentence.

**△ Save report** writes it all to `ms0:/halo/remotepilot-wifi.txt`, with the
network name shortened and the chip's address halved, to read on a PC
without Wi-Fi. (Besides a backup, it is the only file the companion writes;
remote buttons can press △ there too.)

### Viewer API (PSP section)

The viewer's local API (loopback only, with the `X-Remote-Pilot-Viewer: 1`
header, as every `/api/` call):

| Call | Does |
| --- | --- |
| `POST /api/backup` `{}` | Starts a new settings backup on the PSP, then copies and checks it here. `202 {"started": true}`, or `false` if one is already running. |
| `POST /api/backup` `{"folder": "ms0:/BACKUP/flash1-…"}` | Copies and checks a backup already on the card. |
| `GET /api/state` → `backup` | The running or last backup: `{"state": "working"\|"done"\|"failed", "step", "result"}`. |
| `GET /api/backups` | The backups kept here, newest first, each checked again: name, files, bytes, theme, `checked`. The files themselves are never served. |
| `POST /api/action` `{"kind": "files", "payload": "ms0:/BACKUP"}` | Lists the backups on the card (the folder browser's action). |

## Build the companion EBOOT

```bash
python psp/tools/build_psp.py --pspdev <pspdev folder> --make <GNU make>
```

1. Copy `psp/device/build/psp/EBOOT.PBP` and `rp_flash.prx` to `ms0:/PSP/GAME/REMOTEPILOT/`.
2. In the viewer, choose the **PSP · Homebrew (RemotePilot PSP)** preset and **Prepare pairing**.
3. Copy the pairing file it writes to `ms0:/remotepilot/remotepilot.cfg` (the companion also reads the
   earlier `ms0:/halo/remotepilot.cfg`).
4. Start **RemotePilot PSP** from the XMB, and enter the address it shows into the viewer.

## Security

- **Pairing and authentication:** RP2 as in [docs/PROTOCOL.md](pc/docs/PROTOCOL.md). Pairing uses a 32-byte token. Every request and response is signed with HMAC-SHA256, and each connection gets a fresh nonce, so a replayed request is refused (tested).
  - The HMAC-SHA256 is ChupathingyCE's CC0 implementation, the one Sierra-III already compiles. It is copied unchanged to `device/third_party/`, with its licence.
- **New action kinds:**
  - `files` lists a folder (JSON, at most 64 KiB and 256 entries), read-only;
  - `file` sends one whole file (at most 4 MiB; a larger file is refused, never cut), read-only;
  - `backup` copies flash1 into a new `ms0:/BACKUP` folder: the only write, to a fixed new folder, with an empty request body. The settings are opened read-only.
- **Path checks** on the device:
  - paths must start with `ms0:/`;
  - only safe characters are allowed;
  - empty, `.`, `..` and trailing-dot/space components are refused, and so are NUL bytes.
  - The device config, which holds the token, is refused whatever its case.
- **The viewer checks paths again** before sending anything, keeps copies in its ignored `local/captures/`, and serves them with fixed MIME types, `nosniff` and a strict CSP.
- **Network:** the device answers only private IPv4 peers (10/8, 172.16/12, 192.168/16, loopback). The simulator listens on 127.0.0.1 only.
- **Bug reports stay on this computer.** **Options → Write a bug report** saves `report.md` (what you wrote, the preset, device state, browser and time; no device address or pairing) and, if you choose, the device's screen and log, in a new folder under `pc/local/bug-reports/`. Nothing is sent to GitHub or anywhere else; what to do with the folder is up to you. **Save bug capture** stores a screen and log under `pc/local/captures/`. The viewer API: `POST /api/bug-report` `{"what", "steps", "expected", "include"}`, `GET /api/bug-reports`, and `bugReport` in `/api/state`.

## Wi-Fi limits

A PSP-1000 has 802.11b, so expect about 1–2 Mbit/s in practice:
- **Live view:** half-size BMP frames of 98 KB, about 1–2 frames a second on a PSP-1000.
- **Screenshot:** full size (392 KB) takes a few seconds.
- **Whole files:** up to 4 MiB take up to about 30 seconds.

## Try it without a PSP

```bash
python psp/tools/build_sim.py
cd psp/pc && python server.py
```

1. Choose the **PSP · Homebrew (RemotePilot PSP)** preset and **Prepare pairing**.
2. Enter `127.0.0.1` as the device address.
3. Run `psp/device/build/rp2_sim --config pc/local/psp-homebrew/device.cfg --root <a test folder> --flash1 <a stand-in settings folder>`.

Stop the simulator before connecting a real PSP: the viewer tries 127.0.0.1
first, so a running simulator with the same pairing answers in its place.
