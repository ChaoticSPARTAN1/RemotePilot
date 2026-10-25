# RemotePilot for 3DS

The 3DS tools and their original visuals are grouped here, separate from the
general RemotePilot application. Start with [SETUP](docs/SETUP.md).

| Directory | Contents |
| --- | --- |
| `pc/` | Independent MIT PC tool, themed web UI and included presets |
| `apps/` | Main companion build **10**, recovery updater build **9**, 3DSX/SMDH files, SHA-256 receipts and matching GPL source archive |
| `companion/` | GPL-3.0-only native source, original artwork, build scripts, tests and third-party source/notices |
| `docs/` | Setup, security audit, preliminary distribution/license review and release notes |
| `tools/` | Release verification, desktop test compilation and extracted-bundle checks |

Run `python tools/verify_release.py`, then `python build_bundle.py` from this
directory to build the reproducible bundle. The archive includes both CIAs and
their corresponding native source. Pairing, network addresses, game data, saves,
logs, captures and developer tool binaries are excluded.

For desktop regression checks, run `python tools/build_host_tests.py`, then
`python -m unittest test_homebrew -q` from `pc/`. The two Node test scripts in
`pc/` cover input, guidance and themes. `python tools/smoke_bundle.py` builds
twice, checks identical archives and exercises every extracted preset offline.

The public distribution includes the Example and 3DS Homebrew presets. The
private distribution adds Halo, Morrowind and WaW Zombies integration presets;
those presets require matching independently installed device/game builds.
They are not game downloads.

These are preview builds. Builds 7/6 were installed and exercised on an owner's
console; the 8/7 audit builds add receipt recovery hardening and omit third-party
boot-logo data. Their new native binaries have desktop simulation and graphics
coverage, but a fresh physical installation/boot test remains pending. See the
[audit's scope and remaining limits](docs/SECURITY_AUDIT.md).


## Fast game data and launch repair (0.9.1-preview)

Main build 10 and Recovery build 9 retain the existing aircraft/shield HOME
icons, banners and app palettes. They add a generic homebrew system boot-logo
section and defer app switching until normal libctru cleanup. The earlier
no-logo Recovery build produced an owner-reported ErrDisp; physical boot testing
of this repair remains pending. Installation checks alone do not prove boot.

Game assets use a separate **Game assets** panel in the PC tool. Register a
locally owned data directory with `python register_data.py <folder> --target
<game/data> --name <name>` on one command line, then select that package.
Fast authenticated 4 MiB windows are enabled by default, with 64 KiB checked
frames, SD readback hashing, existing-file protection and physical cancellation.
New-model CPU/cache boost is requested by the main app. Files are limited to
2 GiB minus one byte, packages to 64 GiB/8192 files. Recovery remains app-only.
See [GAME_DATA](docs/GAME_DATA.md) for setup and limits.


## Remote diagnostics (0.10.0-preview)

Main build **11**, recovery **10**. Collect supported logs, crash dumps and saved
bug screenshots from the main companion. Copies are read-only, size bounded,
SHA-256 checked and private to the PC. See [diagnostics](docs/DIAGNOSTICS.md).
The existing aircraft/shield artwork and pairing are retained. Hardware
acceptance of these new versions is pending.
