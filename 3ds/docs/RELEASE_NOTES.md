# 0.10.1-preview - 2026-10-25

Main raw version 12; recovery raw version 11. Same title IDs, pairing and original
aircraft/shield artwork. New binaries are desktop-tested previews, not installed
or hardware-tested in this release session. Prior release assets are unchanged.

- Response writes use at most 4 KiB per send, below libctru's 8 KiB IPC-path
  boundary, and handle partial writes and temporary EINTR/EAGAIN errors under
  the original fixed deadline. Authentication and deployment rules are unchanged.
- A production send-loop regression covers large payloads, partial progress,
  temporary errors, deadline exhaustion, closed sockets and permanent errors.
  A signed 120-entry diagnostic catalog regression covers responses over 8 KiB.
- Portable exports now explicitly include diagnostic modules/UI/tests and derive
  release versions from the actual artifact receipt instead of stale constants.
- Hardware evidence for main 11: boot/authenticated arming and direct 512-byte
  text reads completed a 114,901-byte log with full checksum/readback validation.
  This is not file-list, default-large-chunk, image or dump hardware acceptance.
- Main 11's diagnostic listing resets the connection; small requests work. The
  larger SOC send path is a suspected cause, not a proven hardware diagnosis.
  Next-session hardware validation is required before calling this fix accepted.
- Owner diagnostic content and detailed evidence stay private and are not shipped.

# 0.10.0-preview - 2026-10-25

Main raw version 11; recovery raw version 10. Same title IDs and original art.

- Read-only log, Luma dump and saved screenshot collection with local previews.
- Fixed approved catalog; no arbitrary paths, saves, pairing or personal photos.
- Frozen 4 MiB snapshots, signed chunks and whole-file SHA-256 verification.
- Private PC copies; no diagnostic content is bundled or uploaded.
- Deployment/arming gates; recovery remains update only.
- 60 desktop tests pass; new builds need physical startup/collection testing.

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
