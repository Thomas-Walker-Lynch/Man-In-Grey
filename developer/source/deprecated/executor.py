#!/usr/bin/env -S python3 -B
"""
executor.py — StageHand outer/inner executor (MVP; UNPRIVILEGED for now)

Phase 0 (bootstrap):
  - Ensure filter program exists (create default in CWD if --filter omitted)
  - Validate --stage exists
  - If --phase-0-then-stop: exit here (no scan ,no execution)

Phase 1 (outer):
  - Discover every file under --stage; acceptance filter decides which to include
  - Execute each config’s configure(prov ,planner ,WriteFileMeta) into ONE Planner
  - Optionally print the planner; optionally stop

Phase 2 (inner shim in same program for now; no privilege yet):
  - Encode plan to CBOR and hand to inner path
  - Inner decodes to a Journal and can print it
"""

from __future__ import annotations

# no bytecode anywhere
import sys ,os
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE" ,"1")

from pathlib import Path
import argparse
import getpass
import tempfile
import runpy
import subprocess
import datetime as _dt
import stat

# Local module: Planner.py (same directory)
from Planner import (
  Planner ,PlanProvenance ,WriteFileMeta ,Journal ,Command,
)

# -------- default filter template (written to CWD when --filter not provided) --------

DEFAULT_FILTER_FILENAME = "stagehand_filter.py"

DEFAULT_FILTER_SOURCE = """# StageHand acceptance filter (default template)
# Return True to include a config file ,False to skip it.
# You receive a PlanProvenance object named `prov`.
#
# prov fields commonly used here:
#   prov.stage_root_dpath : Path   → absolute path to the stage root
#   prov.config_abs_fpath : Path   → absolute path to the candidate file
#   prov.config_rel_fpath : Path   → path relative to the stage root
#   prov.read_dir_dpath   : Path   → directory of the candidate file
#   prov.read_fname       : str    → filename with trailing '.py' stripped (if present)
#
# Examples:
#
# 1) Accept everything (default behavior):
# def accept(prov):
#   return True
#
# 2) Only accept configs in a 'dns/' namespace under the stage:
# def accept(prov):
#   return prov.config_rel_fpath.as_posix().startswith("dns/")
#
# 3) Exclude editor backup files:
# def accept(prov):
#   rel = prov.config_rel_fpath.as_posix()
#   return not (rel.endswith("~") or rel.endswith(".swp"))
#
# 4) Only accept Python files + a few non-Python names:
# def accept(prov):
#   name = prov.config_abs_fpath.name
#   return name.endswith(".py") or name in {"hosts" ,"resolv.conf"}
#
# Choose ONE 'accept' definition. Below is the default:

def accept(prov):
  return True
"""

# -------- utilities --------

def iso_utc_now_str() -> str:
  return _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def _ensure_filter_file(filter_arg: str|None) -> Path:
  """
  If --filter is provided ,return that path (must exist).
  Otherwise ,create ./stagehand_filter.py in the CWD if missing (writing a helpful template),
  and return its path.
  """
  if filter_arg:
    p = Path(filter_arg)
    if not p.is_file():
      raise RuntimeError(f"--filter file not found: {p}")
    return p

  p = Path.cwd() / DEFAULT_FILTER_FILENAME
  if not p.exists():
    try:
      p.write_text(DEFAULT_FILTER_SOURCE ,encoding="utf-8")
      print(f"(created default filter at {p})")
    except Exception as e:
      raise RuntimeError(f"failed to create default filter {p}: {e}")
  return p

def _load_accept_func(filter_path: Path):
  env = runpy.run_path(str(filter_path))
  fn = env.get("accept")
  if not callable(fn):
    raise RuntimeError(f"{filter_path}: missing callable 'accept(prov)'")
  return fn

def _walk_all_files(stage_root: Path):
  """
  Yield every file (regular or symlink) under stage_root recursively.
  We do not follow symlinked directories to avoid cycles.
  """
  root = stage_root.resolve()
  for dirpath ,dirnames ,filenames in os.walk(root ,followlinks=False):
    # prune symlinked dirs (files can still be symlinks)
    dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath ,d))]
    for fname in filenames:
      p = Path(dirpath ,fname)
      try:
        st = p.lstat()
        if stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
          yield p.resolve()
      except Exception:
        # unreadable/broken entries skipped
        continue

def find_config_paths(stage_root: Path ,accept_func) -> list[Path]:
  out: list[tuple[int ,str ,Path]] = []
  root = stage_root.resolve()
  for p in _walk_all_files(stage_root):
    prov = PlanProvenance(stage_root=stage_root ,config_path=p)
    try:
      if accept_func(prov):
        rel = p.resolve().relative_to(root)
        out.append((len(rel.parts) ,rel.as_posix() ,p.resolve()))
    except Exception as e:
      raise RuntimeError(f"accept() failed on {prov.config_rel_fpath.as_posix()}: {e}")
  out.sort(key=lambda t: (t[0] ,t[1]))   # (depth ,name)
  return [t[2] for t in out]

# --- run all configs into ONE planner ---

def _run_all_configs_into_single_planner(stage_root: Path ,cfgs: list[Path]) -> Planner:
  """
  Create a single Planner and execute each config's configure(prov ,planner ,WriteFileMeta)
  against it. Returns that single Planner containing the entire plan.
  """
  # seed with synthetic provenance; we overwrite per config before execution
  aggregate_prov = PlanProvenance(stage_root=stage_root ,config_path=stage_root / "(aggregate).py")
  planner = Planner(provenance=aggregate_prov)

  for cfg in cfgs:
    prov = PlanProvenance(stage_root=stage_root ,config_path=cfg)
    planner.set_provenance(prov)

    env = runpy.run_path(str(cfg))
    fn = env.get("configure")
    if not callable(fn):
      raise RuntimeError(f"{cfg}: missing callable configure(prov ,planner ,WriteFileMeta)")

    fn(prov ,planner ,WriteFileMeta)

  # annotate meta once ,on the single planner's journal
  j = planner.journal()
  j.set_meta(
    generator_prog_str="executor.py",
    generated_at_utc_str=iso_utc_now_str(),
    user_name_str=getpass.getuser(),
    host_name_str=os.uname().nodename if hasattr(os ,"uname") else "unknown",
    stage_root_dpath_str=str(stage_root.resolve()),
    configs_list=[str(p.resolve().relative_to(stage_root.resolve())) for p in cfgs],
  )
  return planner

# ----- CBOR “matchbox” (simple wrapper kept local to executor) -----

def _plan_to_cbor_bytes(planner: Planner) -> bytes:
  """Serialize a Planner's Journal to CBOR bytes."""
  try:
    import cbor2
  except Exception as e:
    raise RuntimeError(f"cbor2 is required: {e}")
  plan_dict = planner.journal().as_dictionary()
  return cbor2.dumps(plan_dict ,canonical=True)

def _journal_from_cbor_bytes(data: bytes) -> Journal:
  """Rebuild a Journal from CBOR bytes."""
  try:
    import cbor2
  except Exception as e:
    raise RuntimeError(f"cbor2 is required: {e}")
  obj = cbor2.loads(data)
  if not isinstance(obj ,dict):
    raise ValueError("CBOR root must be a dict")
  return Journal(plan_dict=obj)

# -------- inner executor (phase 2) --------

def _inner_main(plan_path: Path ,phase2_print: bool ,phase2_then_stop: bool) -> int:
  """Inner executor path: decode CBOR → Journal; optionally print; (apply TBD)."""
  try:
    data = Path(plan_path).read_bytes()
  except Exception as e:
    print(f"error: failed to read plan file: {e}" ,file=sys.stderr)
    return 2

  try:
    journal = _journal_from_cbor_bytes(data)
  except Exception as e:
    print(f"error: failed to decode CBOR: {e}" ,file=sys.stderr)
    return 2

  if phase2_print:
    journal.print()

  if phase2_then_stop:
    return 0

  # (Stage 3 apply would go here; omitted in MVP)
  return 0

# -------- outer executor (phase 1 & handoff) --------

def _outer_main(stage_root: Path ,accept_func ,args) -> int:
  if not stage_root.is_dir():
    print(f"error: --stage not a directory: {stage_root}" ,file=sys.stderr)
    return 2

  cfgs = find_config_paths(stage_root ,accept_func)
  if not cfgs:
    print("No configuration files found.")
    return 0

  try:
    master = _run_all_configs_into_single_planner(stage_root ,cfgs)
  except SystemExit:
    raise
  except Exception as e:
    print(f"error: executing configs: {e}" ,file=sys.stderr)
    return 2

  if args.phase_1_print:
    master.print()

  if args.phase_1_then_stop:
    return 0

  # Phase 2: encode CBOR and invoke inner path (same script ,--inner)
  try:
    cbor_bytes = _plan_to_cbor_bytes(master)
  except Exception as e:
    print(f"error: CBOR encode failed: {e}" ,file=sys.stderr)
    return 2

  with tempfile.NamedTemporaryFile(prefix="stagehand_plan_" ,suffix=".cbor" ,delete=False) as tf:
    tf.write(cbor_bytes)
    plan_path = tf.name

  try:
    cmd = [
      sys.executable,
      str(Path(__file__).resolve()),
      "--inner",
      "--plan" ,plan_path,
    ]
    if args.phase_2_print:
      cmd.append("--phase-2-print")
    if args.phase_2_then_stop:
      cmd.append("--phase-2-then-stop")

    proc = subprocess.run(cmd)
    return proc.returncode
  finally:
    try:
      os.unlink(plan_path)
    except Exception:
      pass

# -------- CLI --------

def main(argv: list[str] | None = None) -> int:
  ap = argparse.ArgumentParser(
    prog="executor.py",
    description="StageHand outer/inner executor (plan → CBOR → decode).",
  )
  ap.add_argument("--stage" ,default="stage",
                  help="stage root directory (default: ./stage)")
  ap.add_argument(
    "--filter",
    default="",
    help=f"path to acceptance filter program exporting accept(prov) "
         f"(default: ./{DEFAULT_FILTER_FILENAME}; created if missing)"
  )
  ap.add_argument(
    "--phase-0-then-stop",
    action="store_true",
    help="stop after arg checks & filter bootstrap (no stage scan)"
  )

  # Phase-1 (outer) controls
  ap.add_argument("--phase-1-print" ,action="store_true" ,help="print master planner (phase 1)")
  ap.add_argument("--phase-1-then-stop" ,action="store_true" ,help="stop after phase 1")

  # Phase-2 (inner) controls (outer forwards these to inner)
  ap.add_argument("--phase-2-print" ,action="store_true" ,help="print decoded journal (phase 2)")
  ap.add_argument("--phase-2-then-stop" ,action="store_true" ,help="stop after phase 2 decode")

  # Inner-only flags (not for users)
  ap.add_argument("--inner" ,action="store_true" ,help=argparse.SUPPRESS)
  ap.add_argument("--plan" ,default=None ,help=argparse.SUPPRESS)

  args = ap.parse_args(argv)

  # Inner path
  if args.inner:
    if not args.plan:
      print("error: --inner requires --plan <file>" ,file=sys.stderr)
      return 2
    return _inner_main(Path(args.plan),
                       phase2_print=args.phase_2_print,
                       phase2_then_stop=args.phase_2_then_stop)

  # Phase 0: bootstrap & stop (no scan)
  stage_root = Path(args.stage)
  try:
    filter_path = _ensure_filter_file(args.filter or None)
  except Exception as e:
    print(f"error: {e}" ,file=sys.stderr)
    return 2

  if not stage_root.exists():
    print(f"error: --stage not found: {stage_root}" ,file=sys.stderr)
    return 2
  if not stage_root.is_dir():
    print(f"error: --stage is not a directory: {stage_root}" ,file=sys.stderr)
    return 2

  if args.phase_0_then_stop:
    print(f"phase-0 OK: stage at {stage_root.resolve()} and filter at {filter_path}")
    return 0

  # Load acceptance function and proceed with outer
  try:
    accept_func = _load_accept_func(filter_path)
  except Exception as e:
    print(f"error: {e}" ,file=sys.stderr)
    return 2

  return _outer_main(stage_root ,accept_func ,args)

if __name__ == "__main__":
  sys.exit(main())
