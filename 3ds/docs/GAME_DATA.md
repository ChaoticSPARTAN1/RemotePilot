# Registered game assets

Some homebrew CIAs contain only the engine. Their independently obtained data
must also be present in the engine's expected SD folder. This feature transfers
owned, prepared data folders; it does not supply, download or convert games.

1. Keep the game closed. Open main RemotePilot build 10 and press X to arm it.
2. In the PC tool folder, run `python register_data.py <owned-folder> --target
   <game/data> --name <display-name>` on one command line. The folder is the
   contents of the target directory. For an engine expecting `/doom3/base`, use
   `doom3/base` as the target. Nothing is uploaded by registration.
3. In the 3DS Homebrew panel, select the package under **Game assets**, then
   **Transfer game data - Fast**. The local registry contains source paths and
   hashes and remains under ignored `local/homebrew/data-packages`.
4. Leave the app and lid open. Speed is measured payload MiB/s; SD verification
   time is separate. Wait for every file to pass before launching the game.

Fast mode is always selected for this transfer type. It uses 4 MiB authenticated
windows with 64 KiB frames, fresh nonces and exact offsets. Full SHA-256 SD
readback is required before a new file is committed. Existing identical files
are kept; different files stop the package without overwriting them. Saves,
firmware/system directories, pairing files and executables are excluded.
The browser submits package IDs, never arbitrary local filesystem paths.
HMAC authenticates data but does not encrypt this LAN connection.

B on the console or the PC stop button cancels. Temporary `.rph-*.part` files
are retained after failures. After reboot, partial files are not resumed; start
a new transfer after reviewing the console. Previously completed matching files
can be skipped. Lost acknowledgments never trigger automatic write retries.

Limits: 2 GiB minus one byte per file (console stdio compatibility), 64 GiB and
8192 files per registered package. ASCII safe relative paths only. SD free space
is checked per new file. CIA uploads remain separately capped at 512 MiB.
Recovery supports CIA updates of the main app, not game-data transfers.

Desktop tests cover multi-window transfer, matching/different files, invalid
hashes and frame proofs, disarm cancellation, protected paths and recovery
rejection. On-console throughput and long-run reliability require hardware
validation. The original Doom pack is private owner data and is not included.
