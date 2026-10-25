# 0.9.1-preview - 2026-10-25

Main raw title version 10; Recovery version 9. Same title IDs and original HOME
artwork. Hardware boot confirmation is pending after the reported Recovery v8
launch failure. Main 9 was not installed on that console.

- Generic registered game-data packages and default fast 4 MiB transport.
- Checked file commits, existing-file protection, cancellation and measured speed.
- Main app requests supported New-model CPU/cache boost.
- Compatible generic homebrew boot-logo section and deferred app handoff cleanup.
- Native CIA content/section checks block the former missing-logo package.
- New 8-case data regression suite; 51 combined desktop tests passed.
- Both apps and matching GPL source ship together; original logos retained.

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
