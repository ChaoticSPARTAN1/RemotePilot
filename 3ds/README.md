# RemotePilot for 3DS

The 3DS tools and their original visuals are grouped here, separate from the
general RemotePilot application. Start with [SETUP](docs/SETUP.md).

| Directory | Contents |
| --- | --- |
| `pc/` | Independent MIT PC tool, themed web UI and included presets |
| `apps/` | Main companion build **8**, recovery updater build **7**, 3DSX/SMDH files, SHA-256 receipts and matching GPL source archive |
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
