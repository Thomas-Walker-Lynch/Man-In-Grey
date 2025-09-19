#!/usr/bin/env -S python3 -B
"""
ls_stage.py — list staged files and their header-declared install metadata.

Header line format (first line of each file):
  <owner> <permissions> <write_file_name> <target_directory_path>

- owner:               username string (need not exist until install time)
- permissions:         four octal digits, e.g. 0644
- write_file_name:     '.' means use the read file's basename, else use the given POSIX filename
- target_directory_path: POSIX directory path (usually absolute, e.g. /etc/unbound)

Output formats:
- list (default):  "read_file_path: owner permissions write_file_name target_directory_path"
- table:           columns aligned for readability
"""

from __future__ import annotations

# never write bytecode (root/sudo friendly)
import sys ,os
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE" ,"1")

from dataclasses import dataclass
from pathlib import Path
import argparse
import re

# === Stage utilities (importable) ===

def stage_read_file_paths(stage_root: Path)-> list[Path]:
  """Given:   stage_root directory.
     Does:    recursively enumerate regular files (follows symlinks to files), keep paths relative to stage_root.
     Returns: list[Path] of POSIX-order sorted relative paths (no leading slash).
  """
  rels: list[Path] = []
  for p in stage_root.rglob("*"):
    try:
      if p.is_file():  # follows symlink-to-file
        rels.append(p.relative_to(stage_root))
    except (FileNotFoundError ,RuntimeError):
      # broken link or race; skip conservatively
      continue
  return sorted(rels ,key=lambda x: x.as_posix())

@dataclass
class StageRow:
  read_rel: Path                 # e.g. Path("etc/unbound/unbound.conf.staged")
  owner: str                     # token[0]
  perm_octal_str: str            # token[1], exactly as in header (validated ####)
  perm_int: int                  # token[1] parsed as base-8
  write_name: str                # token[2] ('.' resolved to read_rel.name)
  target_dir: Path               # token[3] (Path)
  header_raw: str                # original header line (sans newline)

    # convenience
  def write_abs(self ,root: Path)-> Path:
    return (root / self.target_dir.relative_to("/")) if self.target_dir.is_absolute() else (root / self.target_dir) / self.write_name

# header parsing rules
_PERM_RE = re.compile(r"^[0-7]{4}$")

def parse_stage_header_line(header: str ,read_rel: Path)-> tuple[StageRow|None ,str|None]:
  """Given:   raw first line of a staged file and its stage-relative path.
     Does:    parse '<owner> <perm> <write_name> <target_dir>' with max 4 tokens (target_dir may contain spaces if quoted not required).
     Returns: (StageRow, None) on success, or (None, error_message) on failure. Does NOT touch filesystem.
  """
  # strip BOM and trailing newline/spaces
  h = header.lstrip("\ufeff").strip()
  if not h:
    return None ,f"empty header line in {read_rel}"
  parts = h.split(maxsplit=3)
  if len(parts) != 4:
    return None ,f"malformed header in {read_rel}: expected 4 fields, got {len(parts)}"
  owner ,perm_s ,write_name ,target_dir_s = parts

  if not _PERM_RE.fullmatch(perm_s):
    return None ,f"invalid permissions '{perm_s}' in {read_rel}: must be four octal digits"

  # resolve '.' → basename
  resolved_write_name = read_rel.name if write_name == "." else write_name

  # MVP guard: write_name should be a single filename (no '/')
  if "/" in resolved_write_name:
    return None ,f"write_file_name must not contain '/': got '{resolved_write_name}' in {read_rel}"

  # target dir may be absolute (recommended) or relative (we treat relative as under the install root)
  target_dir = Path(target_dir_s)

  try:
    row = StageRow(
      read_rel = read_rel
      ,owner = owner
      ,perm_octal_str = perm_s
      ,perm_int = int(perm_s ,8)
      ,write_name = resolved_write_name
      ,target_dir = target_dir
      ,header_raw = h
    )
    return row ,None
  except Exception as e:
    return None ,f"internal parse error in {read_rel}: {e}"

def read_first_line(p: Path)-> str:
  """Return the first line (sans newline). UTF-8 with BOM tolerant."""
  with open(p ,"r" ,encoding="utf-8" ,errors="replace") as fh:
    line = fh.readline()
  return line.rstrip("\n\r")

def scan_stage(stage_root: Path)-> tuple[list[StageRow] ,list[str]]:
  """Given:   stage_root.
     Does:    enumerate files, parse each header line, collect rows and errors.
     Returns: (rows, errors)
  """
  rows: list[StageRow] = []
  errs: list[str] = []
  for rel in stage_read_file_paths(stage_root):
    abs_path = stage_root / rel
    try:
      header = read_first_line(abs_path)
    except Exception as e:
      errs.append(f"read error in {rel}: {e}")
      continue
    row ,err = parse_stage_header_line(header ,rel)
    if err:
      errs.append(err)
    else:
      rows.append(row)  # type: ignore[arg-type]
  return rows ,errs

# === Printers ===

def print_list(rows: list[StageRow])-> None:
  """Print: 'read_file_path: owner permissions write_file_name target_directory_path' per line."""
  for r in rows:
    print(f"{r.read_rel.as_posix()}: {r.owner} {r.perm_octal_str} {r.write_name} {r.target_dir}")

def print_table(rows: list[StageRow])-> None:
  """Aligned table printer (no headers, just data in columns)."""
  if not rows:
    return
  a = [r.read_rel.as_posix() for r in rows]
  b = [r.owner for r in rows]
  c = [r.perm_octal_str for r in rows]
  d = [r.write_name for r in rows]
  e = [str(r.target_dir) for r in rows]
  wa = max(len(s) for s in a)
  wb = max(len(s) for s in b)
  wc = max(len(s) for s in c)
  wd = max(len(s) for s in d)
  # e (target_dir) left ragged
  for sa ,sb ,sc ,sd ,se in zip(a ,b ,c ,d ,e):
    print(f"{sa:<{wa}}  {sb:<{wb}}  {sc:<{wc}}  {sd:<{wd}}  {se}")

# === Orchestrator ===

def ls_stage(stage_root: Path ,fmt: str="list")-> int:
  """Given:   stage_root and output format ('list'|'table').
     Does:    scan and parse staged files, print in the requested format; report syntax errors to stderr.
     Returns: 0 on success; 1 if any syntax errors were encountered.
  """
  rows ,errs = scan_stage(stage_root)
  if fmt == "table":
    print_table(rows)
  else:
    print_list(rows)
  if errs:
    print("\nerror(s):" ,file=sys.stderr)
    for e in errs:
      print(f"  - {e}" ,file=sys.stderr)
    return 1
  return 0

# === CLI ===

def main(argv: list[str] | None=None)-> int:
  ap = argparse.ArgumentParser(
    prog="ls_stage.py"
    ,description="List staged files and their header-declared install metadata."
  )
  ap.add_argument("--stage" ,default="stage",help="stage directory (default: ./stage)")
  ap.add_argument("--format" ,choices=["list" ,"table"] ,default="list"
                 ,help="output format (default: list)")
  args = ap.parse_args(argv)
  stage_root = Path(args.stage)
  if not stage_root.exists() or not stage_root.is_dir():
    print(f"error: stage directory not found or not a directory: {stage_root}" ,file=sys.stderr)
    return 2
  return ls_stage(stage_root ,fmt=args.format)

if __name__ == "__main__":
  sys.exit(main())
