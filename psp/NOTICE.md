# Notices: the PSP section

**Licence.** Everything in `psp/` is MIT (the repository's `LICENSE`; the
viewer's copy is `pc/LICENSE`), except the third-party pieces below, which keep
their own licences.

| Piece | Where | Licence |
| --- | --- | --- |
| SHA-256 and HMAC-SHA256, unchanged from ChupathingyCE (commit d98982b8) | `device/third_party/sha256_hmac.c` | CC0 1.0 (`device/third_party/CHUPATHINGYCE-CC0.txt`) |
| Audiowide font, and the glyphs baked from it | `device/ui/fonts/Audiowide-Regular.ttf`, `device/art/fonts/`, part of `device/ui/ui_fonts.c` | SIL Open Font License 1.1 (`device/ui/fonts/OFL.txt`) |
| DejaVu Sans and Sans Bold, and the glyphs baked from them | `device/ui/fonts/DejaVuSans*.ttf`, part of `device/ui/ui_fonts.c` | Bitstream Vera licence with public-domain DejaVu changes (`device/ui/fonts/LICENSE_DEJAVU`) |

`device/ui/ui_fonts.c` is generated from those fonts by `device/ui/make_fonts.py`;
its glyph tables are under the fonts' licences, not MIT. Neither font's name is
used for anything derived from it.

**Art.** The companion's XMB icon and background (`device/art/`) and its screen
backdrop (`device/ui/ui_backdrop.c`) are our own, drawn from shapes and text
by `device/art/make_xmb_art.py` and `device/ui/make_backdrop.py`: no game art,
captures or anyone's logos.

**A built EBOOT** links the PSP SDK (pspsdk, BSD) and newlib; `tools/build_psp.py`
puts their licences, and the fonts', in `licenses/` beside it. Give that folder
with any copy of the EBOOT.

**Trademarks.** PSP and PlayStation are trademarks of Sony Interactive
Entertainment; Halo is a trademark of Microsoft. RemotePilot is not affiliated
with, endorsed by or sponsored by Sony Interactive Entertainment, Microsoft,
Halo Studios or Bungie. Their names are used only to say what the tools work
with. No game data, firmware or code of theirs is included.
