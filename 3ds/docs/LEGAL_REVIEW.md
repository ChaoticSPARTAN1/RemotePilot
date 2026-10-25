# Preliminary license and distribution review — 2026-10-24

This is a quick project-specific licensing review, not legal advice or a legal
clearance opinion. Distribution laws, platform terms and anti-circumvention rules
vary by jurisdiction; that broader question is not resolved by this review.

## Distribution decisions

- The independent PC application remains **MIT**, following the existing public
  RemotePilot repository. Its MIT license is included in `pc/LICENSE`.
- Native companion/recovery code is **GPL-3.0-only** because it incorporates the
  unmodified SHA-256 implementation and an adapted RSF from ankushKun/3dsDL
  commit `87df82d7c80c590311d05b317b161c9087034758`. Attribution and GPL text are
  included. A parent MIT license does not relicense this nested GPL work.
- Both CIAs ship with the matching complete companion source, artwork, scripts,
  dependency information and vendored libctru source in the same downloadable
  bundle. The source archive is also beside the CIAs in `apps/`. This addresses
  the selected network-distribution method in [GPLv3 section 6(d)](https://www.gnu.org/licenses/gpl-3.0.html#section6)
  and the [FSF source-access guidance](https://www.gnu.org/licenses/gpl-faq.html#SourceAndBinaryOnDifferentSites).
- The linked [libctru 2.7.0 source](https://github.com/devkitPro/libctru/tree/v2.7.0)
  is supplied unmodified with its permissive notice. Its pinned archive hash is
  checked by the release verifier. [newlib notices](https://sourceware.org/newlib/COPYING.NEWLIB)
  and the [GCC Runtime Library Exception](https://www.gnu.org/licenses/gcc-exception-3.1.html)
  are reproduced for the toolchain runtimes. Build tools are downloaded separately
  from their pinned upstream releases, not redistributed as executables here.
- Public audit builds omit the packaging tool's third-party boot-logo blob.
  The HOME icons, HOME banners and in-app relay/shield imagery are original
  RemotePilot assets generated with AI assistance. They are supplied under the
  companion's license to the extent rights are held; no exclusive copyright or
  uniqueness claim is made for AI output.
- Names such as Nintendo 3DS, Luma3DS, Halo, Morrowind and WaW identify
  compatibility/integration targets. No affiliation or endorsement is claimed.
  The public release includes only the Example and general Homebrew presets.
  The private release additionally includes the owner's integration presets and
  original UI themes; it does not distribute game builds or retail assets.
- Neither bundle includes Nintendo SDK material, firmware, encryption keys,
  exploits, commercial game CIAs/ROMs, extracted game art/data, saves, captures,
  pairing credentials, console identifiers or private network configuration.

## Limits and follow-up

This review checks documented provenance and packaging, not every jurisdiction's
rules or every transitive toolchain source file. The project supplies an owner-run
application installer on an already configured homebrew device; it does not supply
a firmware modification or a DRM-bypass workflow. Whether a particular owner or
downstream distributor may lawfully use or distribute a particular third-party CIA
requires a separate assessment. Recheck notices and source matching whenever
dependencies, assets or distribution methods change. For commercial deployment
or disputed rights, obtain qualified legal advice.
