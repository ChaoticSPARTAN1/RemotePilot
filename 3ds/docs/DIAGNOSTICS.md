# Remote diagnostics

Main companion build 11 adds authenticated, read-only diagnostic collection.
Recovery build 10 stays limited to updating the main application.

1. Close the game and open main RemotePilot. Press X to arm it.
2. In the PC tool's **3DS Homebrew** section, open **Logs, crash dumps & bug images**.
3. Choose **Refresh files**, select a diagnostic, then **Collect file**.
4. Text and images are previewed; **Download verified copy** exports the exact
   bytes. Binary dumps can be downloaded for symbol analysis. Text previews show
   the last 64 KiB; the complete file is retained up to the 4 MiB per-file limit.

Supported sources: Doom log and stack-near-limit dump; Morrowind log, crash and
watchdog files, Bug It text reports and images; Luma ARM11/ARM9 crash dumps;
Luma, Doom and Morrowind saved screenshots. Owner-saved bug images can also be
placed in `/3ds/RemotePilotHomebrew/bug-images`. The feature reads existing
screenshots. It does not capture a running game, recover unsaved evidence or
operate while the console is on an exception screen. Save a Luma dump with A
before restarting; then reopen the companion.

The device exposes a fixed catalog, not arbitrary SD paths. It skips oversized,
linked and unrelated files, caps listings at 128 and scans at 4096 directory
entries. Each directory contributes up to 24 matching filenames in reverse name
order (not modification-time order). Names are restricted to safe ASCII.
A 4 MiB maximum snapshot is frozen in RAM; signed 32 KiB chunks and a whole-file
SHA-256 check ensure a changing source cannot mix different versions. Disarming
or expiry invalidates the snapshot. Reads are blocked during deployments and
unknown outcomes. Recovery rejects diagnostic actions entirely.

Verified PC copies and metadata stay under ignored
`local/homebrew/diagnostics`; files are not uploaded, deleted or modified on the
console. In-memory UI results are session scoped; saved copies remain on disk.
Logs/dumps/images may contain private game or system information. Review a copy
before sharing it. The public bundle contains no owner diagnostics or pairing.
RPH1 authenticates this local connection; its contents are not encrypted.

Desktop acceptance: 60 protocol/installation/data/diagnostic tests, plus native
display/chainload and existing UI regressions. Physical 11/10 startup and remote
collection still need validation on a console. Main build 10 was previously
confirmed running on hardware; that does not validate the new build.
