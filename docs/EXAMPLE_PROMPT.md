# Example integration request

Use this prompt with a developer working in a homebrew source tree. Replace the
bracketed values with the build's own details. Keep any pairing token and real
network address out of the prompt and out of source control.

> Integrate Remote Pilot into [homebrew project] using the generic RP2 protocol
> and the adapter contract in `docs/PROTOCOL.md` and `docs/INTEGRATION.md`.
> Create a preset with ID [stable-id], display layout [dimensions and optional
> touch region], and only the capabilities implemented by this build. Keep the
> game playable and local controls authoritative. Add an in-game PC link switch
> that defaults off when no private config is present. Parse the generated
> device config at runtime; never commit a token, address, port, capture, log,
> image, audio sample, or game asset. Authenticate every RP2 request and signed
> response, enforce size/time limits, and expire remote held input promptly.
>
> Start with paired discovery, status, and full screenshot. Then add an opt-in
> live image/audio stream, standard controller snapshots, bounded button
> presses, touch coordinates, safe console commands, runtime timing, a recent
> log tail, and a structured bug report. If the game has a local bug action,
> increment `captureSequence` so the PC saves both image and diagnostics.
> Expose optional catalog metadata and a menu-only preview that never launches
> gameplay. Keep captures and owner content on the user's device or in the
> ignored local PC folder.
>
> Provide a first-run guide: install the preset, start the viewer, select it,
> click Prepare pairing, copy the generated config using the folder picker,
> enable the in-game session, and verify connection. Exercise wrong-token,
> session-off, disconnect, reconnect, oversized input, and browser-close cases.
> Record measured frame impact on real hardware. Keep the integration in a
> separate review branch and do not submit a pull request until approved.
