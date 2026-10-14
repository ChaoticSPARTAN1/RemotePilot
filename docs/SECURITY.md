# Security and privacy

Remote Pilot binds its browser server to loopback and chooses a free port when
it starts. The browser API checks the exact local Host, same-origin requests,
and a custom viewer header; it sends no CORS permission. It has no account,
telemetry upload, update service, or internet listener. The reference device
adapter initiates outbound connections only to private local IPv4 addresses.

The optional RP2 transport uses a random 256-bit pairing token, a fresh device
nonce on every connection, HMAC-SHA256 authentication in both directions, and
bounds on messages and timeouts. RP2 authenticates traffic; it does **not**
encrypt it. Use a trusted local network, do not forward the device listener to
the internet, and turn off the device session when remote access is unwanted.
The viewer's PC link switch also pauses its requests. Remote controls remain
off until the user enables them in the focused browser tab.

`local/` is created at runtime and ignored by Git. It holds pairing tokens,
exported device config, captures, logs, request history, cached device
addresses, and theme choices. Do not put `local/` on a shared drive or upload
it with a bug report. The portable builder uses an explicit source whitelist
and never adds files from `local/`, `dist/`, or installed device presets.

Preset adapters are executable Python. Install only code you trust and inspect
its dependencies; an adapter has the same file and network access as the user
running Remote Pilot. A preset's device config destination is validated as a
relative path before the browser writes to a selected storage folder. The
viewer never silently chooses a drive or installs device software.

Before sharing a fork or integration, run the tests and the repository audit in
`docs/INTEGRATION.md`; inspect the exact staged files and the full Git history.
Generated tokens and private network values must be absent from both. Security
tests cannot guarantee that custom adapters or device builds are safe; review
and test each integration separately.
