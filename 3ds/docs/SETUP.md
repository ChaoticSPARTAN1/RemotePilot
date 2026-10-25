# Setup and use

1. Extract the complete bundle, keeping `pc`, `apps` and `companion` together.
2. Install Python 3.11 or newer. Open `pc/run.cmd`, or run
   `python3 pc/receiver.py serve`. Open http://127.0.0.1:38764/ in Chrome.
3. Choose **3DS Homebrew**, expand **Pair companion**, and enter your console's
   numeric private IPv4 address. The PC creates an independent private config
   under `pc/local/homebrew/`. Do not put that directory in Git or share it.
4. For initial setup, copy that config to
   `sdmc:/3ds/RemotePilotHomebrew/remote-pilot-homebrew.cfg`. Copy the main and
   recovery 3DSX/SMDH pairs into their matching folders under `sdmc:/3ds/`, and
   copy the two tool CIAs from `apps/` into `sdmc:/cias/`.
   Check the actual card's identity first. Safely remove it before reinserting
   it in the powered-off console. The optional PowerShell staging scripts also
   verify serial, back up replaced files and preserve pairing/game state.
5. Install **RemotePilotHomebrew.cia** and **RemotePilotUpdater.cia** individually
   through your existing trusted installer. A CIA file on SD is not installed
   until that console operation succeeds. This project does not supply firmware,
   exploits, retail keys, third-party installers or commercial games.
6. Open the teal RemotePilot app and press **X** to arm. Use the main app for
   everyday CIA transfers. Use the amber/purple Recovery app when updating or
   recovering the main companion. Never replace an app while it is running.

The page shows one current action. For a checked install in manual mode, it
flashes **PRESS A ON YOUR 3DS** until the console confirms approval. B rejects
an approval request or acknowledges a completed/stopped result. Historical
receipts remain available after returning to ready. Unknown outcomes require
inspection; acknowledging one does not retry or resume it.

On the main app's ready screen choose **Choose an app to transfer**, select a
trusted owner-built CIA and enter its expected application title ID. You can
transfer only or request installation. The URL option accepts final public
HTTPS URLs on port 443 plus the expected SHA-256/title ID; redirects, private
addresses and environment proxies are disabled. A matching hash verifies exact
bytes, not the safety or publisher of an arbitrary app.

Autonomous installs are optional and off after restart. After arming, use the
page's setup action and press **Y** in the supported console app. New jobs can
then install without A; exact file/title/version/storage checks still apply.
Disarming, restarting or idle expiry removes permission. Disable Luma input
injection before A/Y because HID does not distinguish injected keys.

HOME/Luma input is a separate opt-in feature. Its UDP protocol has no
authentication or delivery acknowledgement. It stays off during transfers;
use it only on a trusted network while watching the console. It does not prove
that HOME is visible and supplies no system video/audio streaming.

The webpage follows the connected tool: main is navy/teal, Recovery is
purple/gold throughout. Switching back restores the main preset's saved colors.
Additional transfer types such as mods/folders/saves are future work; this
release advertises CIA applications only.
