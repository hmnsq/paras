# paras

**Put any software into your language, and prove it still works.** Paras on SHAKTI is Parashakti: the sovereign stack,
from silicon to distribution, in every language Hindawi supports.

```
pipx install paras-ilm
paras ingest https://github.com/OWNER/REPO
paras top                              # watch it, in the manner of htop
```

| Command | What happens |
|---|---|
| `paras ingest <repository>` | BURP puts it into every supported language; each converts back to the original byte for byte, or it is not published; one branch per language |
| `paras report <repository>` | ingest and check only; GAPS.md says what is still to be translated |
| `paras stack` | the whole sovereign stack, layer by layer, silicon to distribution (`paras list`) |
| `paras top` | every core's load, the stack's progress, and each language's quality as BURP measures it; pause, move to other cores |

`<repository>` is any Git URL or a folder. Options: `--langs urdu,tamil`, `--publish [ORG]` (default hmnsq, asks once),
`--only`, `--from`, `--cpus 0-5`, `--local` (no container), `--work DIR` (default `./paras-work`).

Everything runs inside one Docker container that paras makes once and keeps; nothing is installed on your machine and
nothing asks for sudo. Your GitHub login is handed into the container only when you publish, and you are asked once.

## How it is held to account

- A language is published only if it converts back to the original exactly; after a push, the remote is read back and must
  hold exactly the commits pushed.
- Every step is shown as it runs and recorded in `paras-work/events.jsonl`; every failure is recorded with its cause, and one
  package failing never stops the rest. State is written atomically; one run per work folder; a rerun carries on.
- The disk is checked before each package; every command has a time limit; the manifest is validated before anything runs.
- `ops/verify.sh` runs the tests, end to end included; nothing is released unless they pass.

| Claim | State |
|---|---|
| A folder or repository ingested into Urdu, Tamil and Hindi, converting back exactly, published to a stand-in remote and verified | verified (tests) |
| xv6 ingested into all 76 languages, each converting back exactly | verified (AC's run, 21 Oct 2026) |
| SHAKTI bare metal and xv6 from Urdu, Tamil and Hindi on QEMU; darknet from Urdu | verified (earlier runs) |
| The whole stack published to GitHub | not yet run |

© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI. MIT licence. Paras™, Parashakti™, Hindawi™ and BURP™ are his
trademarks. Docker is a trademark of Docker, Inc.; GitHub of GitHub, Inc. Their mention implies no endorsement.
