# Python compression idioms

Run `pip install vulture radon --break-system-packages` (or let
`scripts/dead_code_scan.sh` / `scripts/complexity_report.py` attempt it) before
starting a Python job — these two tools drive most of the automated detection.

## Idioms, roughly in order of typical impact

- **Comprehensions over manual loops** for simple map/filter — but stop if the
  comprehension needs a line-break to stay readable; a 4-line manual loop that
  reads clearly beats a cryptic one-liner. This skill optimizes real bloat, not
  readability.
- **`dataclasses` / `NamedTuple` / `attrs`** instead of hand-written
  `__init__`/`__eq__`/`__repr__` boilerplate classes. `dataclasses` is stdlib
  and usually the right default; reach for `attrs` only if the project already
  depends on it.
- **`itertools`/`functools`** (`groupby`, `chain`, `reduce`, `lru_cache`,
  `partial`) instead of hand-rolled equivalents — a very common source of
  20-line functions collapsing to 3.
- **Context managers (`with`), including custom ones via `contextlib.contextmanager`**
  instead of manual try/finally cleanup blocks repeated across the codebase.
- **`pathlib`** instead of manual `os.path.join`/string-concat path logic.
- **Pydantic (v2) / `dataclasses` + validators** instead of hand-rolled input
  validation functions repeated across multiple endpoints/functions — this is
  usually the single biggest win in a Python API codebase; look for repeated
  `if not x.get(...): raise ValueError(...)` blocks first.
- **Single parameterized function with a dict/enum dispatch** instead of
  near-copies of a function for each "type" (classic
  `if kind == 'a': ... elif kind == 'b': ...` copy-paste sprawl, or worse,
  three whole separate functions — `find_duplicates.py --normalize-literals`
  is tuned to catch exactly this pattern).
- **Decorators** to collapse repeated cross-cutting logic (logging, timing,
  retry, auth checks) that's currently copy-pasted at the top of many
  functions.
- **`functools.singledispatch`** instead of a long `isinstance` if/elif chain
  dispatching on argument type.
- **Structural pattern matching (`match`/`case`, Python 3.10+)** instead of a
  long `if/elif` chain on a value's shape/type — only if the project's minimum
  supported Python version allows it; check `setup.py`/`pyproject.toml`
  `python_requires` before using this.

## Careful with (these are Tier 2/3, not Tier 1 — see risk-classification.md)

- **Generator vs list semantics.** A generator is lazy/one-shot; replacing a
  list-returning function with a generator changes behavior if callers iterate
  it twice or need `len()`/indexing on the result.
- **Bare `except:` clauses.** A bare `except:` that silently swallows errors
  is part of *current* behavior until the user says otherwise. Don't "fix" it
  while compressing — narrowing exception handling is a behavior change, not
  compression, even when it looks like an obvious bug.
- **Mutable default arguments** (`def f(x, cache={})`). If you spot this while
  compressing, it's very likely an existing bug — flag it to the user
  separately rather than silently fixing it as part of a "behavior-preserving"
  pass, and definitely don't introduce a new one while consolidating functions.

## Tooling recap (see metrics-and-tooling.md for full detail)

| Task | Command |
|------|---------|
| Dead code | `vulture <path> --min-confidence 80` |
| Complexity | `python3 scripts/complexity_report.py <path>` (uses radon if installed) |
| Duplication | `python3 scripts/find_duplicates.py <path> --normalize-literals` |
| Tests | `pytest` (or `python -m unittest discover`) |
