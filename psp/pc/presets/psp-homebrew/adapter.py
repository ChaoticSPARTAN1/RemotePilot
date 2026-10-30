"""PSP homebrew over RP2: the RemotePilot PSP companion, or any PSP build that
answers RemotePilot's RP2 protocol (psp/pc/docs/PROTOCOL.md) as the companion's
code does (psp/device). A template: copy this folder under a new id for your
own build, and list only the capabilities it answers.

Pairing writes ms0:/remotepilot/remotepilot.cfg, which the device never lists
or sends."""
from reference_adapter import ReferenceAdapter


def create_adapter(local_dir, manifest):
    return ReferenceAdapter(local_dir, manifest)
