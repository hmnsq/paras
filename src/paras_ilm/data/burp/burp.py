#!/usr/bin/env python3
# © 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI.
"""BURP, the Bidirectional Universal Resource Parser: Hindawi's ingestion pipeline.

  burp.py ingest  SRC --langs all|hindi,bengali,... --out OUT [--scripts bengali,gurmukhi|brahmi] [--rename-files]
                  [--translators glossary,argos,cmd] [--keep REGEX] [-I DIR] [-D NAME[=V]]
  burp.py reverse NATIVE --out OUT          (NATIVE is one OUT/<language> folder BURP wrote)
  burp.py check   SRC --langs all [--scripts brahmi] [--json FILE]   ingest, reverse, compare byte for byte

Ingestion localises an existing project for people; it needs no transliteration. Per file, by its extension
(the paradigm, or shaili), every token outside string literals, comments and #include names is handled thus:
  a keyword       becomes the language's word, from that language's own reverse transducer rules (*2h.uhin);
  an identifier   is translated once per project and language and kept in the project's dictionary;
  an external     (a name the project does not define: system headers, the host's keywords, --keep) stays.
Comments are translated and kept in the dictionary, so the reverse restores them exactly. Build files carry
-D and -U names through the same dictionary. File names are localised only with --rename-files, which renames
the files and rewrites the #include lines and build files that name them. The compilation path is separate:
hindawicc carries native source through Romenagri, which transliterates, so names survive to the symbol table.

Translators, tried in order for every word or phrase not yet in the dictionary:
  glossary  lang/hindawi/tools/tables/identifiers.csv and lang/hindawi/burp/glossary/<language>.tsv
  argos     Argos Translate, offline, if installed with an English to <language> model
  cmd       any program: HINDAWI_TRANSLATE_CMD, with {lang} for the language code, reads lines, writes lines
A word no translator knows stays as it is, and is recorded as such. See docs/hindawi/TRANSLATION-TOOLS.md.
"""
import argparse, csv, json, os, re, shutil, subprocess, sys, unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
HIN = HERE.parent
CELLS, LEGACY = HIN / "languages", HIN / "upstream/chintamani"
DICT_NAME = ".hindawi/dictionary.json"   # where tools/build_project.py and hindawicc read it

# extension: (shaili, reverse transducers in order, comment style); lex and yacc compose with c2h, as in Chintamani
CASELESS = ("basic", "vhdl")   # paradigms whose keywords are matched in any case
PARADIGMS = {}
for exts, shaili, rev, style in [((".c", ".h"), "guru", ["c2h"], "c"),
                                 ((".cpp", ".cc", ".cxx", ".hpp", ".hh"), "shraeni", ["cpp2h"], "c"),
                                 ((".s", ".S", ".asm"), "yantra", ["asm2h"], "asm"),
                                 ((".java",), "kritrima", ["java2h"], "c"), ((".bas",), "praatha", ["b2h"], "basic"),
                                 ((".py",), "soochee", ["py2h"], "py"), ((".y",), "wyaaka", ["yacc2h", "c2h"], "c"),
                                 ((".l",), "shabda", ["l2h", "c2h"], "c"), ((".logo", ".lg"), "robot", ["logo2h"], "logo"),
                                 ((".vhd", ".vhdl"), "vhdl", ["vhdl2h"], "vhdl")]:
    for e in exts:
        PARADIGMS[e] = (shaili, rev, style)
# the original Hindawi reverse transducers, used for Hindi wherever the legacy has them
LEGACY_REV = {"asm2h": "yantra/y2h.uhin", "java2h": "kritrima/j2h.uhin", "c2h": "guru/c2h.uhin", "cpp2h": "shraeni/cpp2h.uhin", "b2h": "praatha/b2h.uhin",
              "py2h": "soochee/py2h.uhin", "yacc2h": "wyaaka/yacc2h.uhin", "l2h": "shabda/l2h.uhin"}
# build systems: make, automake, CMake, Meson, autoconf, Kconfig, SCons, Bazel, Ninja, qmake, GN and Android's; their -D and -U
# names and, with --rename-files, the file names they mention are carried across, and back exactly
BUILD_FILES = re.compile(r"^(GNUmakefile|[Mm]akefile.*|.*\.mk|CMakeLists\.txt|.*\.cmake|meson\.build|meson_options\.txt|meson\.options|"
                         r"configure\.(ac|in)|Kconfig.*|SConstruct|SConscript|BUILD|BUILD\.bazel|WORKSPACE(\.bazel)?|.*\.bzl|.*\.ninja|"
                         r".*\.pr[oi]|.*\.gni?|Android\.bp)$")
ISO = {"hindi": "hi", "bengali": "bn", "urdu": "ur", "tamil": "ta", "telugu": "te", "marathi": "mr", "gujarati": "gu",
       "punjabi": "pa", "kannada": "kn", "malayalam": "ml", "nepali": "ne", "sanskrit": "sa", "odia": "or", "assamese": "as",
       "arabic": "ar", "persian": "fa", "farsi": "fa", "russian": "ru", "chinese": "zh", "japanese": "ja", "korean": "ko",
       "hebrew": "he", "sinhala": "si", "thai": "th", "tibetan": "bo", "burmese": "my", "khmer": "km", "lao": "lo"}
# VHDL's reserved words stay untranslated as identifiers until a language provides its vhdl2h.uhin
VHDL_WORDS = {w for l in (HERE / "paradigms/vhdl_keywords.txt").read_text(encoding="utf-8").splitlines()
              if not l.startswith("#") for w in l.split()} if (HERE / "paradigms/vhdl_keywords.txt").exists() else set()
# C and C++'s own reserved words: in a C or C++ file only these stay as they are (print is Python's, not C++'s)
C_WORDS = set("""alignas alignof and and_eq asm auto bitand bitor bool break case catch char char8_t char16_t char32_t class compl concept
const consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default delete do double dynamic_cast
else enum explicit export extern false float for friend goto if inline int long mutable namespace new noexcept not not_eq nullptr
operator or or_eq private protected public register reinterpret_cast requires restrict return short signed sizeof static
static_assert static_cast struct switch template this thread_local throw true try typedef typeid typename union unsigned using
virtual void volatile wchar_t while xor xor_eq _Bool _Complex _Generic _Noreturn _Static_assert _Thread_local main""".split())
HOST_WORDS = set("""auto break case char const continue default do double else enum extern float for goto if inline int
long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while
_Bool _Complex bool true false NULL main class public private protected virtual namespace template typename this new
delete try catch throw using operator friend import package extends implements interface final abstract boolean byte
def lambda pass yield None True False and or not in is elif from as with global nonlocal assert del raise except
print len range self""".split())
WORD = r"#?[A-Za-z_\u00C0-\u024F\u0300-\u036F\u0370-\u03FF\u0400-\u04FF\u0590-\u06FF\u0700-\u08FF\u0900-\u0DFF" \
       r"\u0E00-\u0FFF\u1000-\u109F\u1780-\u18AF\u1900-\u1CFF\u3040-\u30FF\u3400-\u9FFF\uA800-\uABFF\uAC00-\uD7AF" \
       r"\U00010000-\U0001FFFF][\w\u0300-\u036F\u0900-\u0DFF\u0E00-\u0FFF\u1000-\u109F\u1780-\u18AF\u1A00-\u1CFF" \
       r"\uA800-\uABFF\U00010000-\U0001FFFF\u200C\u200D\uAC00-\uD7AF\u1100-\u11FF\u1900-\u19FF\u3130-\u318F]*"
COMMENTS = {"vhdl": r"--[^\n]*", "c": r"//[^\n]*|/\*[\s\S]*?\*/", "py": r"#[^\n]*", "asm": r";[^\n]*", "logo": r";[^\n]*",
            "basic": r"(?im:^[ \t]*REM\b[^\n]*)|'[^\n]*"}
STRINGS = r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\''
INCLUDE = r'#[ \t]*include[ \t]*[<"][^>"\n]*[>"]'
RULE = re.compile(r'^(\S+)\s+\{\s*printf\("((?:[^"\\]|\\.)*)"\);\s*\}')


def scanner(style):
    parts = [f"(?P<inc>{INCLUDE})"] if style == "c" else []
    if style == "basic":
        # the text after REM is a comment; REM itself is a keyword and is translated like any other
        parts += [f"(?P<com>{COMMENTS[style]}|(?<=[Rr][Ee][Mm])[ \t][^\n]*)", f"(?P<str>{STRINGS})"]
    else:
        parts += [f"(?P<str>{STRINGS})", f"(?P<com>{COMMENTS[style]})"]
    # a number is one token, so 0xFFu or 1e-3f is never read as a name
    number = r"(?P<num>\b0[xX][0-9A-Fa-f]+[uUlL]*\b|\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[uUlLfF]*\b)"
    return re.compile("|".join(parts + [number, f"(?P<word>{WORD})"]))


# A licence obliges its notice to be kept intact (GPL section 1, Apache section 4, BSD clause 1, MIT): never translated.
LEGAL = re.compile(r"(?i)copyright|\(c\)|©|licen[cs]e|spdx|warranty|all rights reserved|permission is hereby granted")


def read_exact(path):
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        return f.read()


def write_exact(path, text):
    with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(text)


def load_rules(path):
    """English word to native word, from one transducer's own rules; plain words only."""
    table = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = RULE.match(line.strip())
        if not m:
            continue
        pat, out = re.sub(r"\\(.)", r"\1", m.group(1)), re.sub(r"\\(.)", r"\1", m.group(2))
        english = re.compile(r"#?[A-Za-z_][A-Za-z0-9_]*")
        if english.fullmatch(out) and (not english.fullmatch(pat) or (out in HOST_WORDS and pat not in HOST_WORDS)):
            # some generated cells are written the other way round (native to English), some emit KW_ placeholders:
            # read them as they are, so their keywords are used rather than lost (docs/hindawi/DEVIATIONS.md)
            pat, out = (out[3:].lower() if out.startswith("KW_") else out), pat
        if len(pat) > 1 and out and english.fullmatch(pat) and pat not in table:
            table[pat] = out
    return table


def keyword_table(lang, rev):
    table = {}
    for r in rev:
        legacy = next((b / LEGACY_REV.get(r, "-") for b in (LEGACY, HIN.parents[1] / ".build/chintamani/Hindawi")
                       if (b / LEGACY_REV.get(r, "-")).exists()), LEGACY / "-")
        src = legacy if lang == "hindi" and legacy.exists() else CELLS / lang / f"{r}.uhin"
        if src.exists():
            for k, v in load_rules(src).items():
                table.setdefault(k, v)
    # a binding is used only if the language's own transducer turns the word back into the keyword: the foundation
    # check records the ones that do not (lang/hindawi/data/roundtrip.json), and those keywords stay in host form
    rt = HIN / "data/roundtrip.json"
    if rt.exists():
        gone = json.loads(rt.read_text(encoding="utf-8")).get(lang, {})
        for r in rev:
            for k in gone.get(r, []):
                table.pop(k, None)
    return table


def script_of(text):
    names = [unicodedata.name(c, "?").split(" ")[0] for c in text if ord(c) > 0x7F and c.isalpha()]
    return max(set(names), key=names.count) if names else None


def project(text, src, dst):
    """Render one Brahmi-derived script in another by Unicode name projection; characters with no counterpart stay."""
    out = []
    for c in text:
        n = unicodedata.name(c, "")
        if n.startswith(src + " "):
            try:
                t = unicodedata.lookup(dst + n[len(src):])
                if unicodedata.name(t, "") == dst + n[len(src):]:   # aliases do not round-trip: leave those alone
                    out.append(t); continue
            except KeyError:
                pass
        out.append(c)
    return "".join(out)


class Translator:
    def __init__(self, lang, order):
        self.lang, self.code, self.order, self.gloss = lang, ISO.get(lang, lang), order, {}
        rows = []
        m = HERE / "glossary/multi.tsv"           # one table, a column per language; identifiers.csv and <lang>.tsv win
        if m.exists():
            t = [l.rstrip("\n").split("\t") for l in open(m, encoding="utf-8") if l.strip() and not l.startswith("# ")]
            if lang in t[0]:
                c = t[0].index(lang)
                rows += [(r[0], r[c]) for r in t[1:] if c < len(r) and r[c]]
        g = HIN / "tools/tables/identifiers.csv"
        if g.exists():
            rows += [(r["english"], r.get(lang)) for r in csv.DictReader(l for l in open(g, encoding="utf-8") if l.strip())]
        u = HERE / "glossary" / f"{lang}.tsv"
        if u.exists():
            rows += [tuple(l.rstrip("\n").split("\t")[:2]) for l in open(u, encoding="utf-8") if "\t" in l]
        self.gloss = {e.lower(): n for e, n in rows if e and n}
        self.argos = None
        if "argos" in order:
            try:
                import argostranslate.translate as at
                self.argos = at
            except Exception:
                pass

    def phrase(self, text):
        t = text.strip()
        if not t:
            return text
        for how in self.order:
            if how == "glossary" and t.lower() in self.gloss:
                return self.gloss[t.lower()]
            if how == "argos" and self.argos:
                try:
                    r = self.argos.translate(t, "en", self.code)
                    if r and r != t:
                        return r
                except Exception:
                    pass
            if how == "llm" and os.environ.get("HINDAWI_LLM_URL"):
                r = self.llm(t)
                if r and r != t:
                    return r
            if how == "cmd" and os.environ.get("HINDAWI_TRANSLATE_CMD"):
                p = subprocess.run(os.environ["HINDAWI_TRANSLATE_CMD"].format(lang=self.code), shell=True,
                                   input=t.encode(), capture_output=True)
                r = p.stdout.decode("utf-8", "replace").strip()
                if p.returncode == 0 and r and r != t:
                    return r
        return None

    def llm(self, text):
        """One call to a local model through an OpenAI-compatible endpoint; the answer is the translation only."""
        import urllib.request
        body = {"model": os.environ.get("HINDAWI_LLM_MODEL", "local"), "temperature": 0,
                "messages": [{"role": "system", "content": f"Translate from English into {self.lang.replace('_', ' ')}, "
                              "in that language's own script. Reply with the translation only, nothing else."},
                             {"role": "user", "content": text}]}
        try:
            req = urllib.request.Request(os.environ["HINDAWI_LLM_URL"], json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)["choices"][0]["message"]["content"].strip().splitlines()[0].strip()
        except Exception:
            return None

    def identifier(self, ident):
        words = [w for w in re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", ident).split("_") if w]
        whole = self.phrase(" ".join(words))
        parts = [whole] if whole else [self.phrase(w) or w for w in words]
        if not whole and parts == words:   # nothing translated: the name stays exactly as it was
            return ident
        native = re.sub(r"[^\w\u0300-\u036F\u0900-\u0DFF\u0E00-\u0FFF\u1000-\u109F\u1780-\u18AF\uA800-\uABFF]+", "_",
                        "_".join(parts)).strip("_")
        return native if native and not native[0].isdigit() else ident


LEXYACC = set("yylex yyparse yyerror yylval yytext yyleng yywrap yyin yyout yylineno YYSTYPE yychar yynerrs yydebug yyrestart "
              "yy_scan_string yy_delete_buffer yy_create_buffer yy_switch_to_buffer YY_BUFFER_STATE yyterminate ECHO BEGIN REJECT yymore yyless unput".split())


def _need_gcc():
    if not shutil.which("gcc") or not shutil.which("g++"):
        sys.exit("burp: gcc and g++ are needed to read the system headers' names (apt-get install gcc g++); nothing was ingested")


def externals(src, includes, defines):
    _need_gcc()
    """Names the project does not define: whatever the system headers declare, by the preprocessor. Kept apart by
    language, so a C++ header's names (swap, first, second, sort) stay English only in C++ files, not in C files."""
    names = {"c": set(), "c++": set()}
    for f in sorted(p for p in Path(src).rglob("*") if p.suffix in (".c", ".h", ".cpp", ".cc", ".hpp")):
        cmd = ["gcc", "-E", "-x", "c++" if f.suffix in (".cpp", ".cc", ".hpp") else "c", str(f)]
        cmd += [f"-I{d}" for d in [str(f.parent), str(src)] + includes] + [f"-D{d}" for d in defines]
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        system = False
        for line in p.stdout.splitlines():
            m = re.match(r'# \d+ "([^"]*)"((?: \d)*)', line)
            if m:
                system = " 3" in m.group(2) or m.group(1).startswith("/usr/"); continue
            if system:
                names["c++" if f.suffix in (".cpp", ".cc", ".hpp") else "c"].update(re.findall(r"\b[A-Za-z_]\w*\b", line))
    # Macros a system header defines (AF_UNIX, WEXITSTATUS, SOCK_STREAM) never reach the preprocessed text, so they are
    # read from the headers' own definitions: only the <...> includes, so the project's own macros are still its names.
    for f in sorted(p for p in Path(src).rglob("*") if p.suffix in (".c", ".h", ".cpp", ".cc", ".hpp")):
        system = re.findall(r"^\s*#\s*include\s*<[^>]+>", f.read_text(encoding="utf-8", errors="replace"), re.M)
        if not system:
            continue
        cpp = f.suffix in (".cpp", ".cc", ".hpp")
        p = subprocess.run(["gcc", "-E", "-dM", "-x", "c++" if cpp else "c", "-"] + [f"-D{d}" for d in defines],
                           input="\n".join(system), capture_output=True, text=True, errors="replace")
        names["c++" if cpp else "c"].update(re.findall(r"^#define (\w+)", p.stdout, re.M))
    # Lex and Yacc files carry C in their prologues: their system headers' names are external too
    for f in sorted(p for p in Path(src).rglob("*") if p.suffix in (".y", ".l")):
        inc = re.findall(r"^\s*#\s*include\s*<[^>]+>", f.read_text(encoding="utf-8", errors="replace"), re.M)
        if inc:
            pre = subprocess.run(["gcc", "-E", "-x", "c", "-"], input="\n".join(inc), capture_output=True, text=True, errors="replace")
            names["c"].update(w for line in pre.stdout.splitlines() if not line.startswith("#") for w in re.findall(r"\b[A-Za-z_]\w*\b", line))
            mac = subprocess.run(["gcc", "-E", "-dM", "-x", "c", "-"], input="\n".join(inc), capture_output=True, text=True, errors="replace")
            names["c"].update(re.findall(r"^#define (\w+)", mac.stdout, re.M))
    names["c++"] |= names["c"]
    # A name the project declares itself (a function it defines, a member or variable it declares) is the project's own,
    # even where a system header happens to use the same word (insert, print, left, right): it is translated, unless the
    # project also uses it qualified (std::left), where it means the header's.
    RESERVED = set("if for while switch return sizeof catch case do else new delete operator template typename using namespace".split())
    declared, qualified = set(), set()
    for f in sorted(p for p in Path(src).rglob("*") if p.suffix in (".c", ".h", ".cpp", ".cc", ".hpp")):
        t = re.sub(r'"(\\.|[^"\\])*"', '""', f.read_text(encoding="utf-8", errors="replace"))
        t = re.sub(r"//[^\n]*|/\*[\s\S]*?\*/", " ", t)
        declared |= set(re.findall(r"\b([A-Za-z_]\w*)\s*\([^;{}()]*\)\s*(?:const\s*)?\{", t))
        declared |= set(re.findall(r"(?:\b(?:int|char|float|double|long|short|bool|auto|void|unsigned|signed)|\b[A-Z]\w*)\s*[*&]*\s*([A-Za-z_]\w*)\s*(?:=|;|\[)", t))
        declared |= set(re.findall(r",\s*[*&]*\s*([A-Za-z_]\w*)\s*=", t))
        qualified |= set(re.findall(r"::\s*([A-Za-z_]\w*)", t))
    own = declared - qualified - RESERVED
    for k in names:
        names[k] -= own
    if any(p.suffix in (".y", ".l") for p in Path(src).rglob("*")):
        for k in names:                    # the names lex and yacc's generated code calls: never translated, even where defined here
            names[k] |= LEXYACC
    return names


REFERENCE = {}      # the fullest keyword sets (Urdu's and Hindi's tables), to tell a keyword left in English from a name
UNSUPPORTED = set(".rs .go .pl .pm .sh .bash .m4 .hs .lhs .adb .ads .f .f90 .f95 .f03 .for .scm .ss .ts .tsx .js .mjs "
                  ".lua .tcl .el .kt .swift .zig .nim .d .cs .rb .php .v .sv .svh .bsv .bs .ml .mli .jl .scala .clj .ex .exs .erl .dart .m .mm".split())


class Ingestion:
    def __init__(self, lang, args, external):
        self.lang, self.args, self.external = lang, args, external
        self.tr = Translator(lang, args.translators.split(","))
        self.keep = [re.compile(k) for k in args.keep]
        # names kept exactly as they are, from a file (one per line): for trees too large for a pattern (a kernel's
        # assembly, linker scripts and build files name hundreds of thousands)
        kf = getattr(args, "keep_file", None)
        self.keep_set = set(Path(kf).read_text(encoding="utf-8").split()) if kf else set()
        self.d = {"language": lang, "identifiers": {}, "comments": {}, "files": {}, "sequences": {}}
        from collections import Counter
        self.gaps = {"names": Counter(), "comments": Counter(), "keywords": Counter(), "collisions": {}, "unsupported": Counter()}
        self.tables, self.natives = {}, set()

    def table(self, rev):
        key = tuple(rev)
        if key not in self.tables:
            self.tables[key] = keyword_table(self.lang, rev)
            self.natives |= set(self.tables[key].values())
        return self.tables[key]

    def name(self, ident):
        ids = self.d["identifiers"]
        if ident not in ids:
            native, k = self.tr.identifier(ident), 1
            base = native
            taken = set(ids.values()) | self.natives
            while native != ident and native in taken:
                k += 1; native = f"{base}_{k}"
            ids[ident] = native
            if k > 1:
                self.gaps["collisions"][ident] = native     # its word was taken (a keyword or another name): a suffix keeps them apart
        if ids[ident] == ident:
            self.gaps["names"][ident] += 1                   # no dictionary entry yet: stays as written
        return ids[ident]

    def comment(self, text):
        m = re.match(r"(//|/\*|#|;|'|REM\b)([\s\S]*?)(\*/)?$", text, re.I)
        if not m:
            return text
        inner = m.group(2)
        if LEGAL.search(inner):                  # copyright and licence notices are kept exactly as their authors wrote them
            return text
        lines = [self.tr.phrase(l) or l if l.strip() else l for l in inner.split("\n")]
        native = m.group(1) + "\n".join(lines) + (m.group(3) or "")
        if native == text and re.search(r"[A-Za-z]{3}", inner):
            self.gaps["comments"][inner.strip()[:100]] += 1      # no translation yet: stays as written
        if native != text:
            if self.d["comments"].get(native, text) != text:
                return text          # another comment already reads this way once translated: this one stays as written
            self.d["comments"][native] = text
        return native

    def source(self, rel, text):
        shaili, rev, style = PARADIGMS[Path(rel).suffix]
        table, seq, ambiguous = self.table(rev), [], {}
        caseless = style in CASELESS
        if caseless:
            table = {k.lower(): v for k, v in table.items()}
        natives = set(table.values())   # every word the reverse could read as a keyword is recorded, so it reads it right
        reference = REFERENCE.setdefault(tuple(rev), {(k.lower() if caseless else k) for l in ("urdu", "hindi") for k in keyword_table(l, rev)})
        for k, v in table.items():
            ambiguous.setdefault(v, []).append(k)

        def sub(m):
            if m.group("word") is None:
                if m.lastgroup == "com":
                    return self.comment(m.group(0))
                if m.lastgroup == "inc":
                    t = m.group(0)
                    if self.args.rename_files:
                        t = re.sub(r'"([^"]+)"', lambda q: '"' + self.renamed(rel, q.group(1)) + '"', t)
                    if t.startswith("#include") and "#include" in table:   # the directive is a keyword; the header is a file
                        seq.append("#include")
                        t = table["#include"] + t[len("#include"):]
                    return t
                return m.group(0)
            w = m.group("word")
            key = w.lower() if caseless else w
            before = m.string[m.start() - 1] if m.start() else ""
            if Path(rel).suffix in (".y", ".l") and before in "%\\[-" and key not in table:
                return w                                  # %left, %token, \n, [a-zA-Z]: the grammar's own notation
            if key in table:
                seq.append(w)
                return table[key]
            if key in reference:
                self.gaps["keywords"][f"{shaili}:{w}"] += 1     # a keyword of the language with no word in this table yet
            if w in natives:            # a name spelled like one of the language's keywords stays itself on the way back
                seq.append(w)
            host = C_WORDS if Path(rel).suffix in (".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh") else HOST_WORDS
            if style == "asm" and w in asm_labels:      # a label the file defines itself is its own name
                return self.name(w)
            if w.startswith("#") or w[0].isdigit() or style == "asm" or w in host or (style == "vhdl" and w.lower() in VHDL_WORDS) or w in self.external["c++" if Path(rel).suffix in (".cpp", ".cc", ".cxx", ".hpp", ".hh") else "c"] \
                    or w in self.keep_set or any(k.search(w) for k in self.keep) or not re.fullmatch(r"[A-Za-z_]\w*", w):
                return w
            return self.name(w)
        asm_labels = set(re.findall(r"^\s*([A-Za-z][A-Za-z0-9]*)\s*:", text, re.M)) if style == "asm" else set()
        out = scanner(style).sub(sub, text)
        if seq:
            self.d["sequences"][rel] = seq
        return out

    def renamed(self, rel, inc):
        target = os.path.normpath(str(Path(rel).parent / inc))
        return os.path.relpath(self.d["files"][target], str(Path(self.d["files"].get(rel, rel)).parent)) \
            if target in self.d["files"] else inc

    def build_file(self, text):
        ids = self.d["identifiers"]
        text = re.sub(r"(-[DU])([A-Za-z_]\w*)", lambda m: m.group(1) + ids.get(m.group(2), m.group(2)), text)
        for orig, native in self.d["files"].items():
            text = re.sub(rf"(?<![\w/.]){re.escape(Path(orig).name)}(?![\w.])", Path(native).name, text)
        return text


def ingest_one(lang, args, external):
    src, out = Path(args.src), Path(args.out) / lang
    if out.exists():
        shutil.rmtree(out)
    ing = Ingestion(lang, args, external)
    files = sorted(p for p in src.rglob("*") if p.is_file() and ".hindawi" not in p.parts and ".git" not in p.parts)   # never the history
    if args.rename_files:
        for p in files:
            if p.suffix in PARADIGMS:
                rel = str(p.relative_to(src)); stem = ing.tr.identifier(p.stem)
                ing.d["files"][rel] = str(Path(rel).with_name(stem + p.suffix))
    written = {}
    for p in files:                      # sources first, so the build files see every identifier's name
        rel = str(p.relative_to(src))
        if p.suffix in PARADIGMS:
            written[rel] = ing.source(rel, read_exact(p))
    for p in files:
        rel = str(p.relative_to(src))
        if rel in written:
            continue
        if BUILD_FILES.match(p.name):
            written[rel] = ing.build_file(read_exact(p))
        else:
            if p.suffix.lower() in UNSUPPORTED:
                ing.gaps["unsupported"][p.suffix.lower()] += 1   # a language BURP cannot read yet: copied as it is
            dst = out / rel; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dst)
    for rel, text in written.items():
        dst = out / ing.d["files"].get(rel, rel); dst.parent.mkdir(parents=True, exist_ok=True)
        write_exact(dst, text)
    script = script_of("".join(ing.natives)) or "LATIN"
    ing.d["script"] = script
    (out / ".hindawi").mkdir(parents=True, exist_ok=True)
    ing.d["forward"] = dict(ing.d["identifiers"]); ing.d["reverse"] = {v: k for k, v in ing.d["identifiers"].items()}
    (out / DICT_NAME).write_text(json.dumps(ing.d, ensure_ascii=False, indent=1), encoding="utf-8")
    g = {k: (dict(v.most_common()) if hasattr(v, "most_common") else v) for k, v in ing.gaps.items()}
    (out / ".hindawi" / "gaps.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in render_targets(args, script):
        alt = Path(args.out) / f"{lang}@{s.lower()}"
        if alt.exists():
            shutil.rmtree(alt)
        shutil.copytree(out, alt)
        for f in alt.rglob("*"):
            if f.is_file() and (f.suffix in PARADIGMS or BUILD_FILES.match(f.name)):
                write_exact(f, project(read_exact(f), script, s))
        d = json.loads((alt / DICT_NAME).read_text(encoding="utf-8")); d["rendered"] = {"from": script, "to": s}
        (alt / DICT_NAME).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return lang, len(written), len(ing.d["identifiers"]), len(ing.d["comments"]), script, g


BRAHMI = ["DEVANAGARI", "BENGALI", "GURMUKHI", "GUJARATI", "ORIYA", "TAMIL", "TELUGU", "KANNADA", "MALAYALAM", "SINHALA"]


def render_targets(args, script):
    if not args.scripts or script not in BRAHMI:
        return []
    want = BRAHMI if args.scripts == "brahmi" else [s.upper() for s in args.scripts.split(",")]
    return [s for s in want if s != script and s in BRAHMI]


def reverse_tree(native, out):
    native, out = Path(native), Path(out)
    d = json.loads((native / DICT_NAME).read_text(encoding="utf-8"))
    lang, ids = d["language"], {v: k for k, v in d["identifiers"].items()}
    files = {v: k for k, v in d["files"].items()}
    if out.exists():
        shutil.rmtree(out)
    for p in sorted(native.rglob("*")):
        if not p.is_file() or ".hindawi" in p.relative_to(native).parts:
            continue
        rel = str(p.relative_to(native)); orig = files.get(rel, rel)
        dst = out / orig; dst.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix not in PARADIGMS and not BUILD_FILES.match(p.name):
            shutil.copy2(p, dst); continue
        text = read_exact(p)
        if "rendered" in d:
            text = project(text, d["rendered"]["to"], d["rendered"]["from"])
        if BUILD_FILES.match(p.name):
            text = re.sub(r"(-[DU])(\S+?)(?=[=\s'\")]|$)", lambda m: m.group(1) + ids.get(m.group(2), m.group(2)), text)
            for orig_f, native_f in d["files"].items():
                text = re.sub(rf"(?<![\w/.]){re.escape(Path(native_f).name)}(?![\w.])", Path(orig_f).name, text)
            write_exact(dst, text); continue
        _, rev, style = PARADIGMS[p.suffix]
        table = keyword_table(lang, rev); inverse = {}
        for k, v in table.items():
            inverse.setdefault(v, []).append(k)
        seq = list(d["sequences"].get(orig, []))

        # a native written as several words (Chintamani's BASIC has "हो तो" for THEN) is read back as one
        multi = sorted((k for k in inverse if re.search(r"\s", k)), key=len, reverse=True)
        scan = re.compile("(?P<multi>" + "|".join(re.escape(k) for k in multi) + ")|" + scanner(style).pattern) if multi else scanner(style)

        # an include line whose directive was localised: the directive comes back, the header is unrenamed
        ninc = sorted((k for k, v in inverse.items() if "#include" in v), key=len, reverse=True)
        if ninc:
            scan = re.compile("(?P<ninc>(?:" + "|".join(re.escape(k) for k in ninc) + r')[ \t]*[<"][^>"\n]*[>"])|' + scan.pattern)

        def sub(m):
            if m.lastgroup == "ninc":
                t = m.group(0); nat = next(k for k in ninc if t.startswith(k)); rest = t[len(nat):]
                if d["files"]:
                    rest = re.sub(r'"([^"]+)"', lambda q: '"' + unrename(d, orig, rel, q.group(1)) + '"', rest)
                return (seq.pop(0) if seq else "#include") + rest
            if m.lastgroup == "multi":
                return seq.pop(0) if seq else inverse[m.group(0)][0]
            if m.group("word") is None:
                if m.lastgroup == "com":
                    return d["comments"].get(m.group(0), m.group(0))
                if m.lastgroup == "inc" and d["files"]:
                    return re.sub(r'"([^"]+)"', lambda q: '"' + unrename(d, orig, rel, q.group(1)) + '"', m.group(0))
                return m.group(0)
            w = m.group("word")
            if w in inverse:
                return seq.pop(0) if seq else inverse[w][0]
            return ids.get(w, w)
        write_exact(dst, scan.sub(sub, text))
    return out


def unrename(d, orig_rel, native_rel, inc):
    target = os.path.normpath(str(Path(native_rel).parent / inc))
    back = {v: k for k, v in d["files"].items()}
    return os.path.relpath(back[target], str(Path(orig_rel).parent)) if target in back else inc


def languages(spec):
    have = sorted(p.name for p in CELLS.iterdir() if p.is_dir() and (p / "c2h.uhin").exists())
    return have if spec == "all" else [l for l in spec.split(",") if l in have or l == "hindi"]


def one_source(args):
    """A single file is ingested as a project of one file; a path that does not exist, or a project with no files, is an error."""
    src = Path(args.src)
    if not src.exists():
        sys.exit(f"burp: {src} does not exist")
    if src.is_file():
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="burp-file-"))
        shutil.copy2(src, d / src.name)
        args.src = str(d)
        return d
    if not any(p.is_file() and ".git" not in p.relative_to(src).parts for p in src.rglob("*")):
        sys.exit(f"burp: {src} holds no files to ingest")
    return None


def cmd_ingest(args):
    langs = languages(args.langs)
    single = one_source(args)
    try:
        return _ingest(args, langs)
    finally:
        if single:
            shutil.rmtree(single, ignore_errors=True)


def _ingest(args, langs):
    ext = externals(args.src, args.I, args.D)
    from concurrent.futures import as_completed
    rows, failed = [], []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:          # each language reports the moment it is done
        futs = {pool.submit(ingest_one, l, args, ext): l for l in langs}
        for f in as_completed(futs):
            lang = futs[f]
            try:
                row = f.result()
            except Exception as e:                                       # one language failing never hides the others
                failed.append(lang)
                print("BURP-PROGRESS " + json.dumps({"lang": lang, "error": f"{type(e).__name__}: {e}"}), flush=True)
                continue
            rows.append(row); _, n, ni, nc, script, g = row
            print("BURP-PROGRESS " + json.dumps({"lang": lang, "script": script, "files": n, "identifiers": ni, "comments_translated": nc,
                  "names_missing": len(g["names"]), "comments_missing": len(g["comments"]), "keywords_missing": len(g["keywords"]),
                  "collisions": len(g["collisions"]), "unsupported": sum(g["unsupported"].values())}, ensure_ascii=False), flush=True)
    rows.sort(key=lambda r: langs.index(r[0]))
    if failed:
        print(f"burp: {len(failed)} languages failed: {', '.join(sorted(failed))}", file=sys.stderr)
    for lang, n, ni, nc, script, g in rows:
        print(f"burp: {lang:18} {script:12} {n} files, {ni} identifiers, {nc} comments translated; still missing: "
              f"{len(g['names'])} names, {len(g['comments'])} comments, {len(g['keywords'])} keywords, {len(g['collisions'])} collisions, "
              f"{sum(g['unsupported'].values())} files in languages BURP cannot read yet")
    write_gaps(Path(args.out), rows)
    if failed:
        sys.exit(2)
    return rows


def write_gaps(out, rows):
    """GAPS.json and GAPS.md: what is still missing, across every language of this ingestion, for the next round of work."""
    from collections import Counter
    total = {"names": Counter(), "comments": Counter(), "keywords": Counter(), "unsupported": Counter()}
    per = {}
    for lang, n, ni, nc, script, g in rows:
        per[lang] = {"files": n, "names_missing": len(g["names"]), "comments_missing": len(g["comments"]),
                     "keywords_missing": sorted(g["keywords"]), "collisions": g["collisions"]}
        for k in total:
            total[k].update({w: 1 for w in g[k]} if k != "unsupported" else g[k])
    doc = {"languages": per, "names_missing_in_how_many_languages": dict(total["names"].most_common(500)),
           "comments_missing_in_how_many_languages": dict(total["comments"].most_common(200)),
           "keywords_missing_in_how_many_languages": dict(total["keywords"].most_common()),
           "files_in_languages_burp_cannot_read": dict(Counter({k: v // max(1, len(rows)) for k, v in total["unsupported"].items()}))}
    out.mkdir(parents=True, exist_ok=True)
    (out / "GAPS.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# What is still missing", "", f"{len(rows)} languages. Each line says in how many languages it is missing.", "",
          "## Files in languages BURP cannot read yet", ""] + [f"- `{k}`: {v} files" for k, v in doc["files_in_languages_burp_cannot_read"].items()] + \
         ["", "## Keywords with no word in a language's table", ""] + [f"- {k}: {v}" for k, v in list(doc["keywords_missing_in_how_many_languages"].items())[:200]] + \
         ["", "## Names with no dictionary entry (the most common first)", ""] + [f"- `{k}`: {v}" for k, v in list(doc["names_missing_in_how_many_languages"].items())[:300]] + \
         ["", "## Comments with no translation", ""] + [f"- {k}: {v}" for k, v in list(doc["comments_missing_in_how_many_languages"].items())[:100]]
    (out / "GAPS.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def cmd_check(args):
    single = one_source(args)
    try:
        return _check(args)
    finally:
        if single:
            shutil.rmtree(single, ignore_errors=True)


def _check(args):
    import filecmp, tempfile
    args.out = args.out or tempfile.mkdtemp(prefix="burp-")
    _ingest(args, languages(args.langs))
    report = []
    for folder in sorted(Path(args.out).iterdir()):
        if not (folder / DICT_NAME).exists():
            continue
        back = reverse_tree(folder, Path(args.out) / ".back" / folder.name)
        src_files = sorted(str(p.relative_to(args.src)) for p in Path(args.src).rglob("*") if p.is_file())
        same = [f for f in src_files if (back / f).exists() and filecmp.cmp(Path(args.src) / f, back / f, shallow=False)]
        d = json.loads((folder / DICT_NAME).read_text(encoding="utf-8"))
        localized = {}
        for f in src_files:
            sfx = Path(f).suffix
            if sfx in PARADIGMS:
                orig = read_exact(Path(args.src) / f)
                nat = read_exact(folder / d["files"].get(f, f))
                localized[PARADIGMS[sfx][0]] = localized.get(PARADIGMS[sfx][0], False) or nat != orig
        report.append({"folder": folder.name, "script": d.get("rendered", {}).get("to", d.get("script")),
                       "files": len(src_files), "exact": len(same), "localised": localized})
    shaili_names = sorted({s for r in report for s in r["localised"]})
    print(f"\n{'folder':28} {'script':11} {'back exact':>11}  localised: " + " ".join(shaili_names))
    for r in report:
        marks = " ".join(("yes" if r["localised"].get(s) else "no ").ljust(len(s)) for s in shaili_names)
        print(f"{r['folder']:28} {str(r['script']):11} {r['exact']:>5}/{r['files']:<5}  {marks}")
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [r for r in report if r["exact"] != r["files"]]
    print(f"\nburp check: {len(report)} ingestions, {len(report) - len(bad)} reverse to the original byte for byte")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("ingest", "check"):
        s = sub.add_parser(name); s.add_argument("src"); s.add_argument("--langs", default="all")
        s.add_argument("--out", required=(name == "ingest")); s.add_argument("--scripts")
        s.add_argument("--rename-files", action="store_true"); s.add_argument("--translators", default="glossary,argos,llm,cmd")
        s.add_argument("--keep", action="append", default=[r"^__"]); s.add_argument("-I", action="append", default=[])
        s.add_argument("--keep-file", help="names to keep exactly, one per line")
        s.add_argument("-D", action="append", default=[]); s.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
        if name == "check":
            s.add_argument("--json")
    r = sub.add_parser("reverse"); r.add_argument("native"); r.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "ingest":
        cmd_ingest(a)
    elif a.cmd == "reverse":
        print(f"burp: reversed into {reverse_tree(a.native, a.out)}")
    else:
        sys.exit(cmd_check(a))
