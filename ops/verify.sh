#!/usr/bin/env bash
# verify.sh: paras's own gate. The command and the engine parse, the engine compiles, the stack is sound, help works.
cd "$(dirname "$0")/.."; f=0
for s in paras engine/paras-engine.sh; do bash -n "$s" && echo "  PASS  $s parses" || { echo "  FAIL  $s parses"; f=1; }; done
./paras --help | grep -q -- "--ingest" && echo "  PASS  paras --help names --ingest" || { echo "  FAIL  paras --help"; f=1; }
python3 - <<'PY' || f=1
import re
s = open("engine/paras-engine.sh", encoding="utf-8").read(); e = s[s.index("<<'ENGINE'") + 10:s.rindex("\nENGINE")]
compile(e, "engine", "exec"); print("  PASS  the engine compiles")
names = re.findall(r'^  "([a-z0-9.\-]+)": \{"needs"', e, flags=re.M)
assert names and names[0] == "shakti-sdk", names[:3]; print(f"  PASS  the stack: {len(names)} projects, the SHAKTI SDK first")
PY
grep -q "^FROM " Dockerfile && echo "  PASS  the container is defined" || { echo "  FAIL  Dockerfile"; f=1; }
exit $f
