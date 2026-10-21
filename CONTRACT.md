# paras: its contract

paras follows the estate's master contract (zistgah/governance) and adds:

1. **Nothing ships unverified.** `ops/verify.sh` (the full test suite, end to end included) passes before any push, release or DOI.
2. **No silent failure.** Every failure is recorded with its cause and shown; a fallback is announced when taken.
3. **The round trip is the gate for publishing.** A language that does not convert back exactly is never published.
4. **Published means verified.** After a push, the remote is read back and must match.
5. **Nothing on the host.** Tools are installed inside the container, which is made once and kept.
6. **One consent per run.** The author's intention is asked for once, covering the whole run.
7. **Everything visible.** Every command is shown; nothing is hidden in /dev/null.

© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI.
