# RemotePilot Homebrew

RemotePilot's separate 3DS companion and Recovery Updater provide paired local
Wi-Fi CIA transfers, verified installation and application launch. Both have
original HOME artwork and native dashboards: teal/silver for the main app,
purple/gold for Recovery. Artwork sources are in `artwork/`.

This release is **0.10.1-preview**, main raw title version **12** and Recovery
version **11**. Main 11 boot, authentication and direct small-chunk text retrieval
were confirmed on hardware. Its diagnostic listing failed; large default reads,
dumps and images were not accepted on hardware. This new 12/11 pair includes
bounded response writes and needs next-session hardware acceptance. Desktop AM
services are simulated and cannot establish console behavior.

| Application | SD base application title | Purpose |
| --- | --- | --- |
| RemotePilot Homebrew | `000400000F3D5200` | Transfer trusted CIA applications; update Recovery |
| RemotePilot Updater | `000400000F3D5300` | Install newer builds of the main companion only |

Neither app replaces itself while running. No firmware changes, arbitrary file
paths, save editing, deletion, uninstall, system-title installation, cartridge
loading, DS/DSi mode support or general video/audio streaming are provided.

## Setup and use

In the complete bundle, read `../docs/SETUP.md` and run the PC tool from
`../pc/run.cmd` or `python3 ../pc/receiver.py serve`. Select **3DS Homebrew** and
prepare your own pairing using the console's private IPv4 address. The generated
`remote-pilot-homebrew.cfg` contains a random secret; never publish it.

For the initial Homebrew Launcher bootstrap, place the main `.3dsx` and `.smdh`
in `sdmc:/3ds/RemotePilotHomebrew/`, together with the pairing config. Recovery's
matching files go in `sdmc:/3ds/RemotePilotUpdater/`. Recovery reuses the main
config. To install HOME applications, use an existing trusted CIA installer
such as FBI to install both bundled CIAs. No installer or firmware is bundled.

Open the main companion, keep it open and press **X** to arm. The PC page guides
connection, selection, transfer, approval and result acknowledgement. Choose a
trusted CIA and exact expected title ID, or a final public HTTPS URL with an
independently known SHA-256 and title ID. Downloads have a 512 MiB limit and
reject redirects, environment proxies and private-network destinations.

The console independently checks title, version, size, SHA-256 and storage,
rehashes before writing, then verifies installed metadata after AM completes.
Manual jobs require **A** after review. Press **B** to acknowledge a reviewed
result; the page waits for authenticated confirmation before advancing. An old
completed result returns to ready instead of appearing as an active transfer.

An unknown outcome requires inspecting the console and installed version first.
Restart never resumes or retries installation/launch. Invalid, truncated or
uncommitted receipts become a non-installable unknown state requiring review.
Do not remove receipts during active work or blindly repeat a failed operation.

### Wireless updates

1. Open and arm the main app. Use the PC page to transfer/install a newer
   Recovery build if needed, approving with A and acknowledging with B.
2. Open Recovery from the page or HOME. Confirm its authenticated identity and
   press X there; arming never carries across apps.
3. Use **Update RemotePilot** to send the newer main build. Review and approve
   with A. Keep power stable and wait for independently verified installation.
4. Reopen the main app and press X for another transfer.

CIA installation updates HOME titles. Homebrew Launcher `.3dsx` copies need a
separate card refresh. `Stage-Companion.ps1` and `Stage-ToolUpdates.ps1` require
explicit card identification, validate paths, preserve pairing/staging and
back up existing files; see their parameters and the setup guide before use.
They do not directly modify installed title databases. No game CIA is bundled.

### Optional autonomous installation

While armed and idle, press **Y** to opt in for that session. Each new job must
also request autonomous installation; existing manual jobs stay manual. X
disarm, restart and idle-session expiry remove permission. No network command
can grant it. Turning the mode off before writing restores A approval.

Libctru HID cannot distinguish physical A/Y from injected input. Disable Luma
InputRedirection before approving or enabling autonomous installation. Console
buttons are an owner workflow, not an independent physical-authentication
factor. Unknown outcomes still require review and never auto-retry.

## Network and display boundaries

RPH1 authenticates both peers and exact message bodies with a fresh challenge
and HMAC-SHA256. It does **not encrypt** transferred contents. Use a trusted
private network; do not port-forward the listener. Pairing secrets are plaintext
on the PC and SD. The console's single listener can still be resource-exhausted
by an untrusted LAN peer. See `PROTOCOL.md` and `../docs/SECURITY_AUDIT.md`.

Optional HOME/system input uses Luma's separate unauthenticated UDP protocol.
Delivery/release has no confirmed acknowledgement; disable InputRedirection in
Rosalina to stop it physically. It is opt in and is not secured by RPH pairing.

Both displays render complete RGB565 frames into off-screen buffers, refresh
buffer pointers after swapping and synchronize to vblank. Owner testing of the
preceding builds confirmed stable screens. A guarded desktop renderer test
checks buffer isolation, bounds and presentation; it cannot reproduce LCDs.

## Build and test

The Windows build expects MSYS2 at `C:\msys64`, devkitARM/libctru 2.7.0,
Python with Pillow, and pinned makerom/bannertool. The distributed binaries use
GCC 16.1 and newlib 4.6.0. Compiler executables are not redistributed.

```powershell
.\Get-BuildTools.ps1
.\build.ps1 -HostTests
Set-Location ..\pc
python -m unittest test_homebrew -q
node test_homebrew_flow.js
node test_pointer_controls.js
```

For this standalone source archive, place the PC test suite beside the project
or use the complete release bundle. Build scripts temporarily alias the source
directory to a free drive letter to accommodate spaces, removing it in finally.
They never move the checkout. Packaging outputs go to `dist/`.

`Get-BuildTools.ps1` verifies pinned downloads before extraction. Asset generation
creates icons, banners and version headers for each variant. The CIA package
uses makerom's generic Homebrew boot logo with its upstream MIT notice;
original HOME and in-app artwork remain unchanged.
`verification.json` checks actual CIA title/version and all six binary hashes.
The pinned makerom supports raw versions 1..15, 1024..1039, etc.; the build fails
on unsupported bits or a metadata mismatch. See `HARDWARE_TESTS.md` before
calling any new binary hardware-verified.

## License

This native application is **GPL-3.0-only**. `NOTICE.md` identifies copied SHA
code/RSF provenance, libctru and runtime notices. Matching source, artwork,
build scripts and pinned libctru source accompany the binaries. The PC program
is independent and MIT licensed. Neither app is an official Nintendo product;
compatibility names do not imply endorsement. See `../docs/LEGAL_REVIEW.md`
for the preliminary distribution review.


### Fast game-data packages

Main build 9 adds registered game assets as a separate transfer from CIA apps.
On the PC, run `python register_data.py <owned-data-folder> --target <game/data>
--name <display-name>` (one line) from the PC tool directory. Registrations stay
in private `local/homebrew/data-packages/`; browsers receive package IDs only.
Select the package under **Game assets** and use **Transfer game data - Fast**.
There is no extra fast-mode checkbox: 4 MiB authenticated windows are the default.
The main app requests the supported New-model CPU/cache boost during its session.

The PC shows measured payload MiB/s, file count and aggregate bytes. Each file is
reread on SD for SHA-256 verification before becoming available to the game.
Existing identical files are skipped; differing files stop without replacement.
Save folders, firmware/system data, executables and credentials are excluded.
Individual files are limited to 2 GiB minus one byte; packages to 64 GiB and
8192 files. Separate CIA deployment retains its existing 512 MiB limit.

Keep the game closed and both endpoints powered while transferring. Cancelled
partial files are retained. A reboot does not resume a partial file; a new
transfer can keep completed matching files. No commercial game data is included
in this repository or release. Physical throughput remains to be measured on
the user's console; desktop simulations do not establish Wi-Fi performance.


### 0.9.1 launch repair

The 9/8 audit packages omitted the application boot-logo section. The owner
reported ErrDisp during Recovery launch; its cause is not confirmed by package
hashes. This revision supplies makerom's generic Homebrew logo instead and uses
libctru's exit-time chainloader so sockets, SD files and graphics are closed
before switching applications. See the included Project_CTR MIT notice for
packaging assets. Do not treat successful installation or an APT acknowledgment
as proof the new application booted; confirm its authenticated identity/build.
