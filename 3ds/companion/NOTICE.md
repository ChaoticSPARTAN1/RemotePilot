# License and origin

RemotePilot Homebrew is a separate companion application, distributed under
GPL-3.0-only. See LICENSE for the full license and disclaimer. Original RemotePilot
companion code and artwork: Copyright (c) 2026 Kevin Boggs.

`source/sha256.cpp` and `source/sha256.hpp` are copied without modification from
3dsDL by ankushKun and its contributors, version 0.8.1, commit
87df82d7c80c590311d05b317b161c9087034758. Their original namespace and comments
are preserved. `companion.rsf` is adapted from that release's
`resources/3dsDL.rsf`, with a distinct identity and reduced service/filesystem
permissions. Source: https://github.com/ankushKun/3dsDL. The installer,
application jump and metadata workflows in 3dsDL were engineering references;
this companion's networking, policy, UI and platform implementation are new.

This is not 3dsDL, Luma3DS, or an official Nintendo application. No Luma source
or third-party modules bundled by 3dsDL (quirc, stb, qrcodegen, etc.) are copied.
The application links devkitPro libctru 2.7.0 by devkitPro and contributors;
its upstream license is reproduced in `third_party/libctru-LICENSE.txt`.
The desktop graphics test also includes the same 2,048-byte default bitmap font
as `tests/libctru-default-font.bin`, extracted from the installed libctru archive,
so native dashboard previews use the console's actual font.
Corresponding companion source is included with this local build.

The matching libctru 2.7.0 source is bundled in `third_party/`, pinned to upstream
tag object/commit 36fe1ada5b7ebe53ba4decda36d764a55f8fefb6. Toolchain runtime notices
for newlib 4.6.0 and the GCC Runtime Library Exception are also reproduced there.
The toolchain executables themselves are not included. The generic Homebrew
boot-logo provenance is noted below; HOME icon/banner and in-app artwork are original
RemotePilot assets, generated with AI assistance and supplied under the companion
license. No exclusive copyright or third-party endorsement is claimed for AI output.

The RemotePilot PC client is independently implemented in the separate
RemotePilot directory and does not import the companion's GPL source.


The CIA packaging includes makerom v0.19.0's generic `Homebrew` boot-logo asset
from 3DSGuy/Project_CTR (`makerom/src/ncch_logo.h`), rather than its Nintendo logo
or an absent logo region. Project_CTR's MIT license is included in
`third_party/Project_CTR-MIT-LICENSE.txt`. The asset is not an affiliation claim.
Source: https://github.com/3DSGuy/Project_CTR/tree/makerom-v0.19.0/makerom
