# paras

**Put any software into your language, and prove it still works.**
Paras on SHAKTI is Parashakti: the whole sovereign stack, from the chip to AI, IoT and robotics.

```
git clone https://github.com/hmnsq/paras && cd paras
./paras --ingest https://github.com/OWNER/REPO
```

That is all. Paras builds its container the first time (you see every step), takes the repository, puts it into every
language Hindawi is ready for, checks that each version converts back to the original byte for byte, builds it through
the original Hindawi pipeline, runs it, compares what it prints with the English build, and writes `paras-work/REPORT.md`.

## The three things it does

| Command | What happens |
|---|---|
| `paras --ingest <repository>` | ingest, check, build, run, compare, report |
| `paras --report <repository>` | ingest and check only; the report lists the words still to be translated, with an issue ready to file |
| `paras --stack` | the whole sovereign stack, layer by layer: each upstream forked into hmnsq, each language on its own branch, published |

`<repository>` is any Git URL (GitHub, GitLab, Bitbucket, your own server) or a folder on your machine.

## Options, when you need them

| Option | Meaning |
|---|---|
| `--langs urdu,tamil` | only these languages (`paras --languages` lists them) |
| `--publish [ORG]` | publish each language as a branch of a fork in ORG (default hmnsq) |
| `--build CMD`, `--run CMD`, `--expect TEXT` | how to build and run it and what it must print, if paras cannot find out itself |
| `--list` | the stack, layer by layer |
| `--status`, `--stop` | where a run is, or stop it; running again carries on from where it stopped |
| `--shell` | a shell inside the container |
| `--local` | run without a container (where Docker is not available, as on Colab) |

What it needs: Docker, and for publishing a GitHub login (`gh auth login`); your login is handed into the container.
Nothing is installed on your machine and nothing asks for sudo. Your intention is asked for once per run, never per step.

## What is shown, and what is not yet

| Claim | State |
|---|---|
| SHAKTI bare metal and xv6, built from Urdu, Tamil and Hindi, booted on QEMU | verified |
| xv6 and darknet from Urdu convert back to upstream byte for byte and print what the English build prints | verified |
| A local project, its build system found by paras, ingested, built and run in Urdu, Tamil and Telugu | verified |
| Any repository through `--report`: ingestion, reversal check, the words still to translate, an issue to file | verified on xv6 |
| The rest of the stack (the SHAKTI SDK, firmware, QEMU, Linux, GCC, LLVM, llama.cpp, llm.c, PyTorch and others) | defined, not yet run |

The process behind it: [docs/PROCESS.md](docs/PROCESS.md). Hindawi itself: https://github.com/hindawiai/hindawi2026.10

© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI. Paras™, Parashakti™ and Hindawi™ are his trademarks.
Docker is a trademark of Docker, Inc.; GitHub of GitHub, Inc. Their mention implies no endorsement.
