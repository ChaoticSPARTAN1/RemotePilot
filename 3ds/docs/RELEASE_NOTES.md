# 3DS 0.8.0 preview

- Main companion raw title version **8**; recovery updater raw version **7**.
- Receipt parsing fails closed on incomplete/malformed records and gives
  uncommitted temporary receipts precedence over older completed records.
- The PC downloader uses public-only pinned DNS, verified HTTPS and no redirects
  or environment proxies. Partial HTTP requests have an I/O deadline.
- Generic CIA-transfer ready screen, persistent result acknowledgement, honest
  progress/ETA and explicit A/B/X/Y instructions with device-confirmed transitions.
- Optional session-scoped autonomous installs; default manual approval remains.
- Main navy/teal and Recovery purple/gold palettes follow their original artwork
  across both LCDs and the entire webpage. Main color preferences are preserved.
- Both native CIAs and matching GPL source are bundled under `3ds/` with the
  independent PC client, original visuals, notices and release hashes.

The private repo includes Example, Halo, Morrowind, WaW Zombies and Homebrew
presets. The public add-on includes Example and Homebrew. Game binaries, game
assets, personal state and credentials are excluded from both.

Only CIA applications are transferred in this release. Additional file categories
are future work. New 8/7 native binaries require a fresh physical installation/
boot check; previously installed 7/6 builds were tested on the owner's console.
