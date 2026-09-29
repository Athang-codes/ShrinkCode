#!/usr/bin/env python3
"""
package_skill.py — build the distributable skill archive for a release.

claude.ai's uploader wants a ZIP whose *root* is a folder named exactly like
the skill — `shrinkcode/SKILL.md`, never `SKILL.md` at the ZIP root — and it
rejects the file when that folder name and the frontmatter `name` disagree
("skill folder name doesn't match the skill name"). The wider skill tooling
consumes those same bytes with a `.skill` extension. This script writes both
from one walk of the tree, so the release asset is reproducible instead of
hand-zipped on someone's desktop:

    python3 scripts/package_skill.py                  # writes dist/
    python3 scripts/package_skill.py --output /tmp/out
    python3 scripts/package_skill.py --list           # what would ship

What never ships: VCS/build cruft (`.git`, `node_modules/`, `__pycache__/`,
`*.pyc`), OS cruft (`.DS_Store`, `Thumbs.db`), the maintainer-only `dev/`
notes, and any previously built archive — so the archive is a pure function of
the published source. Entries are sorted and carry a fixed timestamp, so two
builds of the same commit are byte-identical (a rebuild is never a "change").

Exit code 0 = `dist/shrinkcode.zip` + `dist/shrinkcode.skill` written and
re-opened to prove the layout; 1 = the tree does not satisfy the skill contract
(missing `SKILL.md`, missing frontmatter `name`/`description`, or a folder name
that doesn't match the skill name — all three are upload-rejection causes).
"""
import argparse
import fnmatch
import os
import re
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shrinkcode_config import utf8_stdout  # noqa: E402  (path setup above)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_MD = "SKILL.md"

# Never shipped, at any depth (mirrors anthropics/skills package_skill.py, plus
# the maintainer-only dev/ notes and VCS metadata). `.github/` does ship: the
# README documents the Action in it.
EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", "dev", ".venv", "venv",
                ".mypy_cache", ".pytest_cache"}
EXCLUDE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
EXCLUDE_GLOBS = ("*.pyc", "*.pyo", "*.zip", "*.skill", "*~")
EXEC_SUFFIXES = (".sh",)
FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # the zip epoch — deterministic builds
VALID_NAME = re.compile(r"[A-Za-z0-9._-]+")


def read_frontmatter(skill_md_path):
    """Read the two frontmatter keys the uploader actually validates.

    Deliberately not a YAML parser: `name` is one line, and `description` is
    either inline (`description: ...`) or a folded/literal block scalar
    (`description: >` with the text on the indented lines below) — and in both
    shapes the question is "does real description text exist", which this
    answers without a dependency.
    """
    with open(skill_md_path, encoding="utf-8") as fh:
        text = fh.read()
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    name, has_description, pending_block = None, False, False
    for line in text[3:end].splitlines():
        if line[:1] not in (" ", "\t"):          # a top-level key ends any block
            pending_block = False
            key, _, value = line.partition(":")
            value = value.strip().strip("\"'")
            if key.strip() == "name":
                name = value
            elif key.strip() == "description":
                if value in (">", "|", ">-", "|-", ">+", "|+"):
                    pending_block = True          # text lives on the lines below
                else:
                    has_description = bool(value)
        elif pending_block and line.strip():
            has_description = True
    return {"name": name or "", "has_description": has_description}


def validate_skill(skill_root):
    """(ok, message) — the uploader's rules, applied before you upload."""
    folder = os.path.basename(os.path.abspath(skill_root))
    skill_md = os.path.join(skill_root, SKILL_MD)
    if not os.path.isfile(skill_md):
        return False, f"{SKILL_MD} not found in {skill_root}"
    fm = read_frontmatter(skill_md)
    if fm is None:
        return False, f"{SKILL_MD} has no YAML frontmatter block"
    name = fm["name"]
    if not name:
        return False, "frontmatter has no `name`"
    if not VALID_NAME.fullmatch(name):
        return False, f"invalid characters in skill name: {name!r}"
    if name != folder:
        return False, (f"folder name {folder!r} does not match the skill name "
                       f"{name!r} — claude.ai rejects that upload")
    if not fm["has_description"]:
        return False, "frontmatter has no `description`"
    return True, f"skill {name!r}: frontmatter ok, folder name matches"


def iter_files(skill_root):
    """Published files, as sorted forward-slashed paths relative to skill_root."""
    found = []
    for dirpath, dirnames, filenames in os.walk(skill_root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for filename in sorted(filenames):
            if filename in EXCLUDE_FILES:
                continue
            if any(fnmatch.fnmatch(filename, pat) for pat in EXCLUDE_GLOBS):
                continue
            full = os.path.join(dirpath, filename)
            found.append(os.path.relpath(full, skill_root).replace(os.sep, "/"))
    return sorted(found)


def build_archive(skill_root, skill_name, dest):
    """Write one deterministic ZIP rooted at `<skill_name>/`; return the entries."""
    entries = iter_files(skill_root)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in entries:
            info = zipfile.ZipInfo(f"{skill_name}/{rel}", date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if rel.endswith(EXEC_SUFFIXES) else 0o644) << 16
            with open(os.path.join(skill_root, rel), "rb") as fh:
                zf.writestr(info, fh.read())
    return entries


def verify_archive(zip_path, skill_name):
    """Re-open the archive and check the layout the uploader requires."""
    problems = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        corrupt = zf.testzip()
    if corrupt:
        problems.append(f"corrupt entry: {corrupt}")
    root = f"{skill_name}/"
    outside = [n for n in names if not n.startswith(root)]
    if outside:
        problems.append(f"{len(outside)} entries outside {root}: {outside[:3]}")
    if f"{root}{SKILL_MD}" not in names:
        problems.append(f"{root}{SKILL_MD} missing — the uploader needs SKILL.md at the root")
    leaked = [n for n in names if any(f"/{d}/" in n for d in EXCLUDE_DIRS)]
    if leaked:
        problems.append(f"excluded dirs shipped: {leaked[:3]}")
    return problems, names


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Package the skill folder as the release asset "
                    "(<name>.zip for claude.ai, byte-identical <name>.skill)")
    ap.add_argument("--repo", default=ROOT,
                    help="skill folder to package (default: this checkout's root)")
    ap.add_argument("--output", default=os.path.join(ROOT, "dist"),
                    help="directory for the built archives (default: dist/)")
    ap.add_argument("--list", action="store_true",
                    help="print what would be included and exit")
    args = ap.parse_args()

    skill_root = os.path.abspath(args.repo)
    ok, message = validate_skill(skill_root)
    print(f"{'OK  ' if ok else 'FAIL'}  {message}")
    if not ok:
        return 1

    skill_name = read_frontmatter(os.path.join(skill_root, SKILL_MD))["name"]
    if args.list:
        for rel in iter_files(skill_root):
            print(f"  {skill_name}/{rel}")
        return 0

    os.makedirs(args.output, exist_ok=True)
    zip_path = os.path.join(args.output, f"{skill_name}.zip")
    skill_path = os.path.join(args.output, f"{skill_name}.skill")
    entries = build_archive(skill_root, skill_name, zip_path)
    shutil.copyfile(zip_path, skill_path)  # same bytes, the extension skill tooling expects

    problems, names = verify_archive(zip_path, skill_name)
    total = sum(os.path.getsize(os.path.join(skill_root, rel)) for rel in entries)
    print(f"  {len(names)} files, {total / 1024:.0f} KB of source "
          f"-> {os.path.getsize(zip_path) / 1024:.0f} KB archive (same bytes for both)")
    for path in (zip_path, skill_path):
        print(f"  {path}")
    for problem in problems:
        print(f"FAIL  {problem}")
    if problems:
        return 1
    print(f"verify: every entry is under {skill_name}/ and "
          f"{skill_name}/{SKILL_MD} is present")
    return 0


if __name__ == "__main__":
    sys.exit(main())

