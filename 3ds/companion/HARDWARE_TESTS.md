# Hardware acceptance — pending

New main v6 / updater v5 dashboards and autonomous mode have desktop coverage
only. On 2026-10-24, earlier main v5 / updater v4 were installed wirelessly with
AM completion, installed metadata and authenticated reopened main identity checked.
The owner confirmed the earlier flicker/diagonal-bar correction looked steady.
This does not mark every acceptance item below passed. The user confirmed that
existing 3dsDL and Homebrew Launcher launch manually. Historical setup recorded
Luma 13.4; no firmware/boot change is needed or authorized.

1. Reidentify the owner's SD card by serial, FAT32 and expected card layout.
   Back up any files at this companion's four new destination paths. Verify the
   new binaries against `dist/verification.json` before copying and after copying.
2. Launch `.3dsx` and CIA separately. Confirm visible UI, correct ID/icon, AM/PS
   access, Wi-Fi address, random challenge, authenticated status and wrong-token
   rejection. Confirm unarmed requests cannot upload/install/launch.
3. Send a deliberately wrong hash. Confirm installation never starts and the
   existing installed title/version/save/settings remain unchanged.
4. Send a harmless owner's homebrew CIA with a known newer version. Check title,
   version, free space, full hash, local approval, progress, AM finish and fresh
   installed-version query. Verify real saves and external settings survive.
   Use a disposable test title first. Do not start with Morrowind or Halo.
5. Confirm wrong-title, system-title, self-title, same/older versions and insufficient
   storage all stop without automatic uninstall or an invented success result.
6. Interrupt PC upload, console upload, hashing and AM installation separately.
   Request cancellation at each stage. Inspect exact receipts and installed
   metadata. AM cancellation/interruption is unknown; never promise rollback.
   Restart both sides and confirm nothing resumes automatically.
7. Launch a harmless installed SD application. Test APT refusal and dropped launch
   acknowledgement. For Morrowind/Halo, verify that the **new** actual authenticated
   transport connects after preset handoff. Reopen companion after game exit.
8. With Luma InputRedirection manually enabled, test neutral state, each D-pad
   direction, A/B, touch mapping, HOME press and release. Confirm physical input
   remains usable. Check blur, hidden tab, browser closure, preset change and
   disconnect. Test PC crash/network loss separately; Luma has no proven timeout.
   Keep the physical Rosalina stop available. Never infer HOME visibility from UDP.
9. Disable Luma injection before deployment approval. Confirm that RemotePilot never
   sends game transport input and system input concurrently in its normal UI.
10. Starting with the original companion bootstrap, wirelessly install the distinct
    RemotePilot Updater title (000400000F3D5300 v2), approve with A, and verify its
    installed version. This also serves as the small owner-built test CIA before
    any Morrowind deployment. Launch it by APT and by HOME separately, verify its
    paired identity and press X again. Send the main companion v3, approve and
    verify installed metadata, then reopen the main HOME title. Confirm pairing
    and external game state are unchanged and the HBL bootstrap is still available.
11. Verify updater rejection of system/game/self titles, same/older main versions,
    wrong hashes and unarmed commands. Recover from an intentionally non-starting
    disposable main build by opening the updater manually and installing a corrected
    higher version. Do not interrupt power during real AM commit just to simulate
    a failure; commit interruption remains an unknown outcome without rollback.
12. With companion v3 and updater v2, inspect both LCDs at idle, during hashing,
    during approval and during transfer. Confirm the bootstrap's reported flicker
    and diagonal bar are gone and artwork/text stay stable. Desktop buffer tests
    do not establish the appearance or timing of the physical screens.
13. On main v6 / updater v5, verify the teal main and amber recovery dashboards,
    readable progress, full fingerprint, next-action card, and persistent A/X/B
    cue. Confirm both framebuffers stay steady while input is required.
14. Confirm autonomous mode is off at every launch. X arms, then Y enables the
    optional session mode. Test one disposable newer owner-built title without A,
    requiring the same hash/title/version/storage/AM/post-install checks. Confirm
    legacy/manual jobs still require A, revocation before writes falls back to A,
    and X/restart/idle expiry remove permission. No unknown outcome may resume.
    Updater autonomous mode must still reject every target except the companion.

DS/DSi/TWiLight, cartridge launches, system screen/audio streaming, arbitrary-game
compatibility and persistent cross-application networking require separate work.
They are not included as passing or advertised capabilities in this preview.

Record future results with date, exact console/model/firmware/Luma, binary hashes,
title/version and observed outcome in a private local receipt. Use placeholders
for device addresses, card identities and tokens in any shareable record.
