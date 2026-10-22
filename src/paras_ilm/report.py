"""report: REPORT.md for one package. What was done, what every measure means, and for every gap what to do about it and
where. Nothing here is a bare number: each count comes with its meaning and its remedy.
© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI. Licensed under the MIT licence (see LICENSE)."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

SHAILI = {"guru": ("C", "c2h.uhin", "h2c.uhin"), "shraeni": ("C++", "cpp2h.uhin", "h2cpp.uhin"), "kritrima": ("Java", "java2h.uhin", "h2java.uhin"),
          "soochee": ("Python", "py2h.uhin", "h2py.uhin"), "praatha": ("BASIC", "b2h.uhin", "h2b.uhin"), "robot": ("LOGO", "logo2h.uhin", "h2logo.uhin"),
          "yantra": ("assembly", "asm2h.uhin", "h2asm.uhin"), "shabda": ("Lex", "l2h.uhin", "h2l.uhin"), "wyaaka": ("Yacc", "yacc2h.uhin", "h2yacc.uhin")}
EXT = {".rs": "Rust", ".go": "Go", ".pl": "Perl", ".pm": "Perl", ".sh": "shell", ".bash": "shell", ".m4": "m4", ".ac": "autoconf", ".am": "automake",
       ".cmake": "CMake", ".hs": "Haskell", ".lhs": "Haskell", ".adb": "Ada", ".ads": "Ada", ".f": "Fortran", ".f90": "Fortran", ".f95": "Fortran",
       ".f03": "Fortran", ".for": "Fortran", ".scm": "Scheme", ".ss": "Scheme", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
       ".mjs": "JavaScript", ".lua": "Lua", ".tcl": "Tcl", ".el": "Emacs Lisp", ".kt": "Kotlin", ".swift": "Swift", ".zig": "Zig", ".nim": "Nim",
       ".d": "D", ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".v": "Verilog", ".sv": "SystemVerilog", ".svh": "SystemVerilog", ".bsv": "Bluespec",
       ".bs": "Bluespec", ".ml": "OCaml", ".mli": "OCaml", ".jl": "Julia", ".scala": "Scala", ".clj": "Clojure", ".ex": "Elixir", ".exs": "Elixir",
       ".erl": "Erlang", ".dart": "Dart", ".m": "Objective-C", ".mm": "Objective-C++"}
BURP_REPO = "https://github.com/hmnsq/burp"
MEANING = """## What each measure means

- **Names translated**: of the program's own names (its functions, variables, types), the share that have a word in the
  language's dictionary. A name without one stays as written, so the program reads partly in English until the dictionary has it.
- **Comments translated**: of the comments, the share that have a translation.
- **Keywords missing**: words of the programming language itself (such as `if`, `while`, `printf`, `MOV`) for which this
  language's tables have no word yet, so they stay in English wherever they appear.
- **Collision**: two different names were given the same word, or a name was given a word that is already a keyword. BURP
  keeps them apart by adding a suffix (for example `گرہ_2`), so the program still builds, but it reads poorly. The remedy is a
  different word for one of them in the dictionary.
- **Round trip**: whether the language version, converted back by BURP, is the original byte for byte. Only a language whose
  round trip is exact is ever published; anything else is a defect to report.
- **Score**: the mean of names translated, comments translated and the round trip (100 when exact, 0 otherwise). It is for
  sorting only; the parts above say what to fix.
"""


def _lang_gaps(out, lang):
    p = Path(out) / lang / ".hindawi" / "gaps.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _dictionary(out, lang):
    p = Path(out) / lang / ".hindawi" / "dictionary.json"
    return json.loads(p.read_text(encoding="utf-8")).get("identifiers", {}) if p.exists() else {}


def render(p, pin, quality, out, gaps, source):
    qs = sorted(quality.values(), key=lambda q: q.lang)
    done = [q for q in qs if not q.error]
    exact = [q for q in done if q.total >= 0 and q.exact == q.total]
    avg = lambda f: (sum(f(q) for q in done) / len(done)) if done else 0.0
    L = [f"# {p.name}, in {len(qs)} languages", "",
         f"Upstream {p.url} at `{pin}`; ingested `{p.scope}`; layer {p.layer}; from {source}. Each language that converts back "
         f"exactly is published on its own branch, `lang/<language>`: check one out and the code is in that language, the rest of the "
         f"tree is the upstream's.", "",
         f"**{len(exact)} of {len(done)} languages convert back exactly.** On average {avg(lambda q: q.names_pct):.1f}% of names and "
         f"{avg(lambda q: q.comments_pct):.1f}% of comments are in the language; what to do about the rest is below.", "", MEANING,
         "## Every language", "", "| Language | Round trip | Names translated | Comments translated | Keywords missing | Collisions | Score |",
         "|---|---|---|---|---|---|---|"]
    L += [f"| {q.lang} | {q.round_trip if not q.error else 'failed: ' + q.error} | {q.names_pct:.1f}% | {q.comments_pct:.1f}% | {q.keywords_missing} | "
          f"{q.collisions} | {q.score} |" for q in qs]
    L += ["", "## What to do next, most important first", ""]
    n = 1
    bad = [q for q in qs if q.error or (q.total >= 0 and q.exact != q.total)]
    if bad:
        L += [f"### {n}. Round trips that are not exact: a defect, never published", ""]
        for q in bad:
            what = q.error or f"{q.total - q.exact} of {q.total} files differ after converting back"
            L.append(f"- **{q.lang}**: {what}. File it at {BURP_REPO}/issues/new?title={quote(f'Round trip: {p.name} in {q.lang}')} "
                     f"with this report and GAPS.json attached.")
        L.append(""); n += 1
    names = Counter(gaps.get("names_missing_in_how_many_languages", {}))
    if names:
        L += [f"### {n}. Names that need a word in the dictionaries", "",
              f"Each name below stays as written in the languages counted. Add a line `name<TAB>word` to "
              f"`src/burp_ilm/burp/glossary/<language>.tsv` in {BURP_REPO} (a pull request, or an issue with the words), or run with "
              f"`HINDAWI_LLM_URL` set so BURP's translator proposes them for review. The most common first:", ""]
        L += [f"- `{w}`: missing in {c} languages" for w, c in names.most_common(30)]
        if len(names) > 30:
            L.append(f"- and {len(names) - 30} more, all in GAPS.json")
        L += ["", "Per language: " + ", ".join(f"{q.lang} {q.names_missing}" for q in sorted(done, key=lambda q: -q.names_missing)[:20]), ""]
        n += 1
    kw = Counter(gaps.get("keywords_missing_in_how_many_languages", {}))
    if kw:
        L += [f"### {n}. Keywords with no word yet in a language's tables", "",
              "Each keyword below stays in English in the languages counted. Add its word to that language's two tables in the "
              "canonical Hindawi, `lang/hindawi/languages/<language>/<table>` in https://github.com/hindawiai/hindawi2026.10 (both "
              "directions); paras and BURP take it from there:", ""]
        by = defaultdict(list)
        for k, c in kw.most_common():
            sh, _, word = k.partition(":")
            by[sh].append((word, c))
        for sh, words in by.items():
            name, rev, fwd = SHAILI.get(sh, (sh, "the reverse table", "the forward table"))
            L.append(f"- **{name}** (tables `{rev}` and `{fwd}`): " + ", ".join(f"`{w}` ({c})" for w, c in words[:25]) +
                     (f", and {len(words) - 25} more" if len(words) > 25 else ""))
        L.append(""); n += 1
    coll = [(q.lang, _lang_gaps(out, q.lang).get("collisions", {})) for q in done]
    coll = [(l, c) for l, c in coll if c]
    if coll:
        L += [f"### {n}. Collisions: names that had to be told apart with a suffix", "",
              "For each, give one of the two a different word in `src/burp_ilm/burp/glossary/<language>.tsv`:", ""]
        for lang, c in coll:
            ids = _dictionary(out, lang)
            items = []
            for ident, native in list(c.items())[:12]:
                base = native.rsplit("_", 1)[0]
                other = next((k for k, v in ids.items() if v == base and k != ident), None)
                why = f"`{base}` is already the word for `{other}`" if other else f"`{base}` is a keyword or a name the code takes from a library"
                items.append(f"`{ident}` became `{native}` because {why}")
            L.append(f"- **{lang}**: " + "; ".join(items) + (f"; and {len(c) - 12} more" if len(c) > 12 else ""))
        L.append(""); n += 1
    com = Counter(gaps.get("comments_missing_in_how_many_languages", {}))
    if com:
        L += [f"### {n}. Comments not yet translated", "",
              "Add the whole comment, as written, with its translation to the language's dictionary file, or run with `HINDAWI_LLM_URL` "
              "set. The commonest:", ""]
        L += [f"- \"{t}\": missing in {c} languages" for t, c in com.most_common(10)]
        L.append(""); n += 1
    uns = gaps.get("files_in_languages_burp_cannot_read", {})
    if uns:
        langs = Counter()
        for ext, c in uns.items():
            langs[EXT.get(ext, ext)] += c
        L += [f"### {n}. Files in languages BURP cannot read yet", "",
              "These were copied as they are, in English. Each language below needs a BURP paradigm (its keyword tables and comment "
              f"rules); propose one at {BURP_REPO}/issues:", ""]
        L += [f"- {name}: {c} files" for name, c in langs.most_common()]
        L.append(""); n += 1
    if n == 1:
        L += ["Nothing: every language converts back exactly and nothing is missing.", ""]
    L += ["Everything above, in full, is in GAPS.json beside this report.", "",
          "© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI. Made by paras with BURP. Paras™, BURP™ and Hindawi™ are his trademarks."]
    return "\n".join(L) + "\n"
