# Parashakti: the process

© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI.

Parashakti takes software that a sovereign stack depends on, puts it into a language with Hindawi, proves it builds and
runs as the English does, and publishes the result where anyone can check it. One script, `scripts/parashakti.sh`.

## 1. Check the machine (a minute, nothing installed)

`bash parashakti.sh --check` probes every tool, QEMU's SHAKTI machine, the network to GitHub and GitLab, sudo and the
disk, each in limited time. `--install` then tries what is missing, one package at a time; a package that will not install
is reported and the next is tried. A project runs only where its needs are met, and says what it lacks otherwise.

## 2. Ingest, lower, build, test, layer by layer

For each project in the manifest (`bash parashakti.sh --list`), from the firmware up: the SHAKTI SDK and OpenSBI (layer 9,
firmware and boot), QEMU (layer 8, the machine), xv6, MINIX and Linux (layer 10, operating systems), wasm3 (layer 11,
runtimes), binutils, TinyCC, GCC and LLVM (layer 12, toolchains). Each is fetched at a pinned point, built once in English
as the baseline, then for each ready language:

1. ingested with BURP (the keywords, and the names where the build files allow);
2. reversed with BURP and compared with the upstream, byte for byte, file by file;
3. lowered as a whole tree through the original Hindawi pipeline and built with the project's own tools;
4. run (on QEMU, or as a program) and its output compared with the English build's.

A run is verified only when all four hold. `REPORT.md` records each run with its evidence and its AyeKnow state.

## 3. Publish: a fork, one branch per language

`bash parashakti.sh --publish ORG` (after one typed PUSH) publishes each verified project under ORG:

- a fork of the upstream on GitHub (or a mirror, when the upstream lives elsewhere), whose `main` follows the upstream;
- one branch per language, `lang/<language>`: check out a branch and you have the source in that language;
- a default branch `parashakti` with the README, the evidence, `sync.sh` and its scheduled workflow, which every day ingests
  the upstream's new head into each language, tests it, and pushes each branch.

`--mint` then deposits each language's branch with misty, behind a typed MINT, for a DOI. `--publish-to DIR` rehearses the
whole publication into local repositories first.

## 4. What is shown, and what is not yet

Shown here: SHAKTI bare metal and xv6, in Urdu, Tamil and Hindi, verified on QEMU; xv6 in Urdu reversing to its upstream
byte for byte in all 65 C files and printing the same lines as the English build; publishing rehearsed into local
repositories. Not yet run: the SHAKTI SDK, OpenSBI, QEMU, binutils, MINIX, Linux, GCC and LLVM; the scheduled workflow on
GitHub; minting.
