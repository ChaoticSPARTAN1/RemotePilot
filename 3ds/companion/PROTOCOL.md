# RPH1 / homebrew-v1

RPH1 is separate from RP1, legacy game transport and Luma UDP. The app listens
on its paired port (default 38765). The PC targets a numeric private IPv4 address;
there is no broadcast discovery or fallback to an unrelated device.

Each TCP connection accepts one command, with a four-second total socket deadline.
The server obtains a fresh 32-byte nonce from PS_GenerateRandomBytes. If random
generation or required services fail, no authenticated session is accepted.
The secret is a 32-byte random pairing token in a private config file; hex below
always means lowercase ASCII. Secrets never appear in JSON status or logs.

```text
S: RPH1 CHALLENGE <nonce64> <HMAC(token,"server:"+nonce)>\n
C: RPH1 <requestId16> <action> <length> <SHA256(body)> <proof64>\n<body>
S: RPH1 <sameRequestId16> <length> <SHA256(body)> <proof64>\n<JSON body>
```

Client proof covers
`request:<nonce>:<id>:<action>:<decimalLength>:<bodySHA256>`.
Server proof covers `response:<nonce>:<id>:<decimalLength>:<bodySHA256>`.

New status responses additionally report `applicationTitleId`, `buildVersion`,
`updater` and `updateTarget`. The recovery updater (000400000f3d5300) permits
only upload/install/launch of the main companion (000400000f3d5200); the main
companion still rejects its own running title. Legacy status without identity
is treated as main bootstrap only. Both applications read the existing main
pairing config; each has independent staging/receipts and starts disarmed.
The PC confirms an application handoff only when the expected authenticated
identity connects, independently of APT's launch-preparation acknowledgement.
Headers are bounded to 256 bytes; requests to 65,664 bytes; responses to 262,144
bytes. Both sides authenticate the digest and check exact received bytes. A new
connection's nonce prevents replay of a captured signed request. No automatic
mutation retry is permitted after a timeout.

The PC serializes TCP calls to the single-threaded listener. Read-only status,
title and exact-job queries can retry brief transport resets up to twelve times
within a six-second retry budget (an individual socket call stays bounded);
authentication/protocol failures never retry. Each mutation is sent once. If its
acknowledgement is lost, an authenticated exact-job receipt must match the job ID,
title, version, total size, expected state and (for chunks) exact next offset before
the worker can continue to a different command. It never resends that mutation.
Any mismatch or unreadable outcome stops unknown. Launch remains conservative
because the companion may disappear before its receipt can be read. New device
builds half-close successful replies and give post-SD-work acknowledgements their
own four-second socket window. Older bootstrap writes use 16 KiB chunks; the
updated main companion can use the original 64 KiB bound.

| Command | Body | Effect |
| --- | --- | --- |
| status | empty | protocol, live capabilities, armed flag, latest job |
| titles | empty | at most 512 installed SD base-application IDs and versions |
| begin | jobId32 size sha256 titleId16 version [autonomous] | arm required; optional mode requires session opt-in on console |
| chunk | `jobId32 offset\n` then binary bytes | exact sequential offset; max 65,536 bytes |
| verify | jobId32 | flush, incremental hash, AM metadata/version/space checks |
| install | jobId32 | verified-only; manual A approval, or recheck/install under explicit autonomous session permission |
| job | jobId32 | exact job's current outcome |
| cancel | jobId32 | acknowledged outcome; AM cancellation is conservatively unknown |
| launch | requestJobId32 titleId16 | arm, installed-title and APT-prepare checks, acknowledge, then jump |

The device rehashes after approval, logs installation intent before AM writes,
streams in 64 KiB steps, requires every FS write to report its full size, commits
with AM_FinishCiaInstall, then queries installed metadata. No application save
or settings archive is opened. Application jump success must be established by
the target game's paired transport, not the companion's disappearance.

## Optional autonomous installs (main v6 / updater v5)

Every process starts with autonomous permission off. After X arms the session,
Y enables autonomous installs while no job is busy and no outcome is unknown.
The status reports `autonomousSupported` and `autonomousEnabled`; no RPH
command grants this permission. HID does not distinguish local from injected Y,
so disable Luma InputRedirection when changing mode. This owner workflow is not
an independent physical-authentication factor. A new `begin` must explicitly append
`autonomous`. Legacy requests remain manual even while the session mode is on.
The PC captures the current mode when creating a job and appends that suffix
only when both authenticated status fields are true. Job JSON and receipts
record `approvalMode` as `manual` or `autonomous`.

An autonomous `install` still requires the verified exact file, and performs the
same second SHA-256, CIA identity/version, storage, AM commit and installed-version
checks. Y turns permission off. Before AM writes, revocation falls back to A
approval; it never approves an older manual job retroactively. If writes already
started, turning auto mode off affects future jobs; B requests cancellation with
the same conservative outcome rules. X disarm, process restart and fifteen idle
minutes remove permission. Successful file-transfer/hash/install progress renews
the idle timer, so an actively progressing long upload does not expire between
verification and its install request. Status reads do not renew it. A restored
receipt never restores permission or resumes an uncertain job.

PC states include receiving, downloading, queued, uploading, verifying, verified,
awaiting-approval, rechecking, installing, uploaded, installed, cancelled, failed,
unknown, interrupted and launching. Remote AM failure/uncertain cancellation is
unknown. Boot/restart reads receipts but never resumes a mutation. A human must
inspect an unknown device outcome before clearing it.

The Python adapter's `homebrew_request(action, object)` is a deliberately separate
contract. `PluginRuntime` validates its manifest capabilities. Device capabilities
are then negotiated from an authenticated status result. HTTP viewer CSRF/origin,
LAN-cookie and PC link checks still apply. `upload` and `install` are independently
required for jobs that request both. Ordinary `request(kind, payload)` is unchanged.

See sibling `RemotePilot/ADAPTER_API.md` for PC endpoint request shapes.

## Reviewed outcomes and ready display (main v7 / updater v6)

Job JSON includes `reviewed`. The optional tenth receipt column is `reviewed`
or `pending`; older eight/nine-column receipts remain readable. The earlier
`owner-reviewed-unknown-outcome` marker also counts as acknowledged. Unknown
outcomes never inherit acknowledgement or become ready automatically.

B acknowledges a failed or completed result without erasing its title, version,
hash, state or original error. An acknowledged result stays queryable in history,
while both LCDs return to a generic ready display without stale progress or target.
Cancelled jobs also return to ready. Acknowledgement persists after restart;
arming and autonomous permission still start off. `readyForTransfer` reports an
armed session showing this idle display. New transfers create a fresh receipt.

The PC opens with a general CIA-app transfer action. It refreshes installed title
inventory when connecting to an app, so FBI-installed versions are recognised.
Mods, folders and save-file transfers are future work and are not advertised as
supported capabilities. The main app accepts permitted SD base-application CIAs;
the recovery updater remains restricted to the main companion.


## Fast game data (main build 9)

Only the main companion advertises `data-transfer` and `fastDataTransfer:true`.
Recovery remains restricted to updating the main companion. No arbitrary remote
file read, delete, shell command or archive extraction is exposed.

`data-begin` has three ASCII lines: `<id32> <size> <sha256>`, a relative target
root, and a relative file path. `data-status`, `data-end`, and `data-cancel` accept
that file job ID (`data-status` also accepts an empty body). Status includes an
exact identity/hash/target/path/size/offset receipt. Files are limited to 2 GiB
minus one byte for console stdio compatibility. Paths are constrained to safe
ASCII segments. Save folders, firmware/system roots, pairing folders,
credentials and executable extensions are rejected. `3ds` targets must have the
form `3ds/<app>/data`.

`data-stream` is a normal authenticated RPH1 request with the body
`<id32> <offset> <count>`, count at most 4 MiB. After a signed `phase:ready`
response, each frame is a 64-character HMAC followed by up to 65536 bytes. The
frame size is implicitly the lesser of 65536 and remaining window bytes.
The HMAC message is `data:<nonce>:<job>:<offset>:<size>:<SHA256(frame)>`.
The connection ends with a signed data-job receipt. Ten-second frame deadlines,
physical B/X cancellation and bounded windows keep the transfer controllable.
The PC never retries writes; after an interrupted acknowledgment it continues
only if an authenticated exact receipt confirms the complete window offset.

A new file is written exclusively to a unique `.rph-<id>.part`, flushed and
reread for SHA-256 verification before rename. Existing files are rehashed:
identical files are kept; different files stop the package without replacement.
Cancelled/failed partial files stay on SD for inspection, outside the engine's
normal filenames. Reboot does not resume a partial file. A new checked transfer
can skip already committed matching files. Keep the game closed until complete.
HMAC authenticates traffic; this existing LAN protocol does not encrypt it.
The PC shows measured payload throughput separately from file verification.
