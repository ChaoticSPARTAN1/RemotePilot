# Security and safety review — 2026-10-24

This is a source review, targeted adversarial testing and release-content audit,
not an independent certification, a guarantee against console damage or a full
assessment of every third-party component. Reviewed scope: the PC HTTP gateway,
RPH1 client/native server, CIA metadata and install state machine, local staging,
web guidance, release exporter and bundled artifacts.

## Findings corrected before this distribution

| Finding | Impact | Correction and evidence |
| --- | --- | --- |
| Partially parsed SD receipts could leave an active state at startup | A torn write could crash recovery instead of blocking uncertain work | Read into a separate bounded record; require valid fields and limits; invalid records become a non-installable unknown tombstone; malformed/truncated/oversized/numeric/error-token cases tested |
| An old completed receipt could hide an uncommitted temporary receipt | An interrupted write-ahead record could be overlooked | Temporary receipt takes precedence and always requires review; conflicting completed/active records tested |
| URL downloader accepted destinations on local/private networks and environment proxies | The authenticated URL feature could reach unintended services | Require public-only DNS results, pin the numeric connection address, preserve original-host TLS validation/SNI, disable environment proxies/redirects, require HTTPS port 443; private/mixed/mapped/multicast DNS and TLS/pinning tests |
| Incomplete PC HTTP requests had no general I/O deadline | Slow clients could hold handler threads | Accepted viewer sockets now time out; a real partial-header connection test verifies closure |
| Historical acknowledged failures dominated the current UI | Owners could mistake an old failed transfer for current work | Persistent reviewed flag, generic ready view, history retained, matching native restart and web-flow tests |

## Safeguards checked

- PC viewer binds to loopback by default. Host/origin checks, a required custom
  POST header and restrictive response headers defend browser access. Optional
  LAN viewing needs a short-lived paired viewer session. Trusted local processes
  still have localhost access; this is not an OS sandbox.
- RPH1 uses a fresh random challenge, independent 256-bit pairing key, HMAC
  request/response proofs, bounded authenticated payloads and exact chunk offsets.
  It authenticates and checks integrity; it does **not encrypt** file contents.
- Device production paths are fixed. Launch arguments cannot redirect SD writes.
  No remote arbitrary filesystem path, shell, delete, firmware, save-edit or
  uninstall operation exists in the companion.
- App installs require an armed session, a permitted SD base-application title,
  exact version/hash, free space, a second pre-install hash and AM completion plus
  fresh installed-version confirmation. System titles and the running app are
  rejected. Recovery accepts only the main companion title.
- Unknown outcomes never automatically resume or retry mutations. Desktop
  restart, failed AM finish/cancellation and lost acknowledgements stay explicit.
  Only exact authenticated receipts can confirm a missing acknowledgement.
- Autonomous permission starts off, needs a console Y opt-in and an explicit
  per-job request, and expires with the session. Manual jobs are not retroactively
  approved. Status reads do not renew idle permission.
- Staging scripts reidentify the owner's FAT32 card by serial, reject escaping
  or linked paths, verify backups and final hashes, and preserve unrelated game
  state. They do not directly edit installed title databases.
- Release files use an explicit allowlist, per-file SHA-256 manifest, CIA metadata
  checks, matching-source comparison and actual local secret-value scanning
  without printing those secrets. Runtime state is excluded from both repos.

## Remaining boundaries

Arbitrary CIA content is not sandboxed or vouched for; install only trusted
software. Pairing secrets are plaintext on the owner's PC/SD and must be kept
private. Trusted Python adapters are executable code. A nearby unauthenticated
peer can still attempt resource exhaustion of the console's single TCP listener;
use a trusted private network, not port forwarding or a hostile shared network.

Luma InputRedirection is unauthenticated UDP with no confirmed release/delivery;
it remains a separate explicit owner-controlled feature. Libctru HID cannot
distinguish local and injected A/Y. Never describe those buttons as an independent
physical authentication factor. A power failure during AM commit can remain
unknown even with receipts. Tests simulate AM; they do not exhaust physical SD,
firmware, sleep/power-loss or every console model scenario.

The preceding 7/6 builds have owner-device installation and main/recovery boot
evidence. This audited 8/7 binary pair includes new recovery and packaging changes
and is published as a **preview pending a fresh hardware install/boot test**.

## Validation recorded for this release

The development PC suite passed **95 Python tests**. After relocating the public
bundle, all **43 homebrew tests** passed against freshly compiled desktop native
simulations, with no skipped tests. The production renderer buffer regression
and Node instruction/ETA/input/theme tests also passed. Both private and public
bundles were built twice with identical bytes, extracted into a new temporary
directory, verified against their complete manifests and started offline.
Every included preset adapter loaded, and both fixed bundled updates were
discovered with their correct title/version metadata. No device install or
hardware mutation was performed by these release checks.

The final export scan compared each bundle against four actual local credential
values without disclosing those values, in addition to private-key/token pattern
checks. CI repeats manifest/source checks, desktop simulations, Node checks and
extracted-bundle startup. CI has no console credentials or device access.


## 2026-10-25 game-data and launch changes

- Local CLI registrations are validated and private. HTTP accepts package IDs
  only; the companion accepts constrained relative data paths and rejects saves,
  system/firmware roots, credentials, executables, traversal and linked parents.
- Windows batch authentication covers nonce, job, exact offset, frame size and
  SHA-256. No writes retry automatically. Lost acknowledgments require an exact
  authenticated full-window offset. No new authentication bypass or remote arm.
- New files use exclusive unique temporary paths, flush/readback hashing and a
  final rename. Different existing files never get replaced. Cancellation keeps
  committed originals and partial files. Reboot does not resume unfinished data.
- CIA uploads, launches, pairing changes and injected input are blocked during
  data work. Recovery does not expose the data capability. Source/target limits
  and per-file free-space checks bound operations.
- New native packaging checks verify CIA content hashes, NCCH identity, extended
  header, compatible boot-logo section and every ExeFS payload. The exact owner
  Recovery v8 failed the new missing-logo gate. This is a packaging risk found,
  not proof of the ErrDisp's cause. Read-only Windows FAT32 scan found no errors.
- App switching now queues libctru's exit-time chainloader rather than jumping
  during an active network callback. Production-platform regression checks that
  preparation does not start the transition and launch exits the main loop.
- ARM builds and 51 desktop protocol/install/data tests passed; graphics and
  deferred-launch regression passed. New-model boost is requested by the main
  app. Hardware boot/switch/throughput acceptance is still pending for 10/9.
- The prepared owner's Doom pack was staged separately to an identified SD card,
  with all 397 files verified and original saves/logs excluded. Those files and
  all private staging reports are excluded from both distributions.


## 2026-10-25 diagnostics review

Fixed source catalogs on both sides exclude saves, pairing/configuration and
DCIM. Approved Bug It reports exclude receiver.cfg. No request accepts local or
SD paths. Linked ancestors/files, large files, malformed IDs, offsets and
unsigned responses are rejected. Device snapshots are bounded, invalidated on
disarm, and never written back to their sources. Deployments block collection.
The browser uses textContent and local image blobs, never log HTML. PC copies
are private ignored runtime data. Existing authentication and physical arming
are retained; recovery does not expose this capability. Nine new diagnostic
tests cover gates, mutation consistency, corruption, source exclusions, Bug It
and private end-to-end collection; 60 combined tests passed. Physical acceptance
is pending.
