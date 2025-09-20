#!/usr/bin/env -S python3 -B
"""
Man_In_Grey.py — orchestration entrypoint

Phase 0 (bootstrap):
  - Ensure acceptance filter exists (create default in CWD if --input_acceptance omitted)
  - Validate --stage
  - If --phase-0-then-stop: exit here (no scan ,no execution)

Phase 1 (outer):
  - Discover every file under --stage; acceptance filter decides which to include
  - Execute each config’s configure(prov ,planner ,WriteFileMeta) into ONE Planner
  - Optionally print the planner; optionally stop

Phase 2 (apply):
  - Encode plan to CBOR
  - Prefer piping CBOR to privileged gasket at release/<arch>/man_in_grey_apply
  - Else fall back to release/python3/executor_inner.py --plan -
"""

from __future__ import annotations

# no bytecode anywhere
import sys ,os
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE" ,"1")

from pathlib import Path
import argparse
import getpass
import runpy
import subprocess
import datetime as _dt
import platform
import stat as _stat

# Local model types (Planner.py beside this file during dev; in release it’s also shipped)
from Planner import (
  Planner
  ,PlanProvenance
  ,WriteFileMeta
  ,Journal
  ,Command
)

# ---------- constants ----------

DEFAULT_FILTER_FILENAME = "Man_In_Grey_input_acceptance.py"

DEFAULT_FILTER_SOURCE = """# Man_In_Grey acceptance filter (default template)
# Return True to include a config file ,False to skip it.
# You receive a PlanProvenance object named `prov`.
#
# Common fields:
#  prov.stage_root_dpath : Path
#  prov.config_abs_fpath : Path
#  prov.config_rel_fpath : Path
#  prov.read_dir_dpath   : Path
#  prov.read_fname       : str
#
# 1) Accept everything (default):
# def accept(prov):
#   return True
#
# 2) Only a namespace:
# def accept(prov):
#   return prov.config_rel_fpath.as_posix().startswith("dns/")
#
# 3) Exclude editor junk:
# def accept(prov):
#   r = prov.config_rel_fpath.as_posix()
#   return not (r.endswith("~") or r.endswith(".swp"))
#
def accept(prov):
  return True
"""

# ---------- small utils ----------

def iso_utc_now_str()-> str:
  return _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def _repo_root_from(start: Path)-> Path|None:
  cur = start.resolve()
  for p in (cur ,*cur.parents):
    if (p/"release").is_dir():
      return p
  return None

def _norm_arch_name()-> str:
  m = (platform.machine() or "").lower()
  table = {
    "amd64": "x86_64"
    ,"x64": "x86_64"
    ,"x86_64": "x86_64"
    ,"i386": "i686"
    ,"i486": "i686"
    ,"i586": "i686"
    ,"i686": "i686"
    ,"arm64": "aarch64"
    ,"aarch64": "aarch64"
    ,"armv7l": "armv7l"
    ,"armv6l": "armv6l"
    ,"riscv64": "riscv64"
    ,"ppc64le": "ppc64le"
    ,"powerpc64le": "ppc64le"
    ,"s390x": "s390x"
  }
  return table.get(m ,m or "unknown")

def _ensure_filter_file(filter_arg: str|None)-> Path:
  if filter_arg:
    p = Path(filter_arg)
    if not p.is_file():
      raise RuntimeError(f"--input_acceptance file not found: {p}")
    return p
  p = Path.cwd()/DEFAULT_FILTER_FILENAME
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
  root = stage_root.resolve()
  for dirpath ,dirnames ,filenames in os.walk(root ,followlinks=False):
    # prune symlinked dirs
    dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath ,d))]
    for fname in filenames:
      p = Path(dirpath ,fname)
      try:
        st = p.lstat()
        if _stat.S_ISREG(st.st_mode) or _stat.S_ISLNK(st.st_mode):
          yield p.resolve()
      except Exception:
        continue

def find_config_paths(stage_root: Path ,accept_func)-> list[Path]:
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
  out.sort(key=lambda t: (t[0] ,t[1]))   # breadth-first ,then lexicographic
  return [t[2] for t in out]

def _run_all_configs_into_single_planner(stage_root: Path ,cfgs: list[Path])-> Planner:
  agg = PlanProvenance(stage_root=stage_root ,config_path=stage_root/"(aggregate).py")
  planner = Planner(provenance=agg)
  for cfg in cfgs:
    prov = PlanProvenance(stage_root=stage_root ,config_path=cfg)
    # requires Planner.set_provenance(prov) (already added previously)
    planner.set_provenance(prov)
    env = runpy.run_path(str(cfg))
    fn = env.get("configure")
    if not callable(fn):
      raise RuntimeError(f"{cfg}: missing callable configure(prov ,planner ,WriteFileMeta)")
    fn(prov ,planner ,WriteFileMeta)
  j = planner.journal()
  j.set_meta(
    generator_prog_str="Man_In_Grey.py"
    ,generated_at_utc_str=iso_utc_now_str()
    ,user_name_str=getpass.getuser()
    ,host_name_str=os.uname().nodename if hasattr(os ,"uname") else "unknown"
    ,stage_root_dpath_str=str(stage_root.resolve())
    ,configs_list=[str(p.resolve().relative_to(stage_root.resolve())) for p in cfgs]
  )
  return planner

def _plan_to_cbor_bytes(planner: Planner)-> bytes:
  try:
    import cbor2
  except Exception as e:
    raise RuntimeError(f"cbor2 is required: {e}")
  return cbor2.dumps(planner.journal().as_dictionary() ,canonical=True)

# ---------- apply paths ----------

def _find_apply_cmd(repo_root: Path)-> Path|None:
  arch = _norm_arch_name()
  cand = repo_root/"release"/arch/"man_in_grey_apply"
  if cand.exists() and os.access(cand ,os.X_OK):
    return cand
  return None

def _find_inner_py(repo_root: Path)-> Path|None:
  cand = repo_root/"release"/"python3"/"executor_inner.py"
  return cand if cand.is_file() else None

def _apply_via_gasket(cbor_bytes: bytes ,apply_cmd: Path ,args)-> int:
  cmd = [str(apply_cmd)]
  if args.phase_2_print:      cmd.append("--phase-2-print")
  if args.phase_2_then_stop:  cmd.append("--phase-2-then-stop")
  # fine-grained gates (optional pass-through if gasket proxies them)
  if args.phase_2_wellformed_then_stop: cmd.append("--phase-2-wellformed-then-stop")
  if args.phase_2_sanity1_then_stop:   cmd.append("--phase-2-sanity1-then-stop")
  if args.phase_2_validity_then_stop:  cmd.append("--phase-2-validity-then-stop")
  if args.phase_2_sanity2_then_stop:   cmd.append("--phase-2-sanity2-then-stop")
  proc = subprocess.run(cmd ,input=cbor_bytes)
  return proc.returncode

def _apply_via_inner_py(cbor_bytes: bytes ,inner_py: Path ,args)-> int:
  cmd = [
    sys.executable
    ,str(inner_py)
    ,"--plan" ,"-"
  ]
  if args.phase_2_print:      cmd.append("--phase-2-print")
  if args.phase_2_then_stop:  cmd.append("--phase-2-then-stop")
  if args.phase_2_wellformed_then_stop: cmd.append("--phase-2-wellformed-then-stop")
  if args.phase_2_sanity1_then_stop:   cmd.append("--phase-2-sanity1-then-stop")
  if args.phase_2_validity_then_stop:  cmd.append("--phase-2-validity-then-stop")
  if args.phase_2_sanity2_then_stop:   cmd.append("--phase-2-sanity2-then-stop")
  proc = subprocess.run(cmd ,input=cbor_bytes)
  return proc.returncode

# ---------- CLI / orchestration ----------

def main(argv: list[str]|None=None)-> int:
  ap = argparse.ArgumentParser(
    prog="Man_In_Grey.py"
    ,description="Man_In_Grey orchestrator (discover → plan → CBOR → apply)"
  )
  ap.add_argument("--stage" ,default="stage"
                  ,help="stage root directory (default: ./stage)")
  ap.add_argument("--input_acceptance" ,default=""
                  ,help=f"path to acceptance filter exporting accept(prov) "
                        f"(default: ./{DEFAULT_FILTER_FILENAME}; created if missing)")
  ap.add_argument("--phase-0-then-stop" ,action="store_true"
                  ,help="stop after arg checks & filter bootstrap (no stage scan)")
  # Phase-1 controls
  ap.add_argument("--phase-1-print" ,action="store_true"
                  ,help="print master planner (phase 1)")
  ap.add_argument("--phase-1-then-stop" ,action="store_true"
                  ,help="stop after phase 1")
  # Phase-2 controls (forwarded to gasket/inner)
  ap.add_argument("--phase-2-print" ,action="store_true"
                  ,help="print decoded journal (phase 2)")
  ap.add_argument("--phase-2-then-stop" ,action="store_true"
                  ,help="stop after phase 2 decode")
  ap.add_argument("--phase-2-wellformed-then-stop" ,action="store_true")
  ap.add_argument("--phase-2-sanity1-then-stop"   ,action="store_true")
  ap.add_argument("--phase-2-validity-then-stop"  ,action="store_true")
  ap.add_argument("--phase-2-sanity2-then-stop"   ,action="store_true")
  # Optional explicit paths
  ap.add_argument("--apply-cmd" ,default=""
                  ,help="override path to privileged gasket (pipes CBOR to stdin)")
  ap.add_argument("--inner-py" ,default=""
                  ,help="override path to executor_inner.py (fallback path)")

  args = ap.parse_args(argv)

  # Repo root
  repo_root = _repo_root_from(Path.cwd()) or _repo_root_from(Path(__file__).resolve()) or Path.cwd()

  # Phase 0 bootstrap
  stage_root = Path(args.stage)
  try:
    filter_path = _ensure_filter_file(args.input_acceptance or None)
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
    print(f"phase-0 OK: stage at {stage_root.resolve()} ,filter at {filter_path}")
    return 0

  # Acceptance
  try:
    accept_func = _load_accept_func(filter_path)
  except Exception as e:
    print(f"error: {e}" ,file=sys.stderr)
    return 2

  # Phase 1: discover + plan
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

  # Phase 2: encode + apply
  try:
    cbor_bytes = _plan_to_cbor_bytes(master)
  except Exception as e:
    print(f"error: CBOR encode failed: {e}" ,file=sys.stderr)
    return 2

  # Prefer gasket; else fall back to Python inner
  apply_cmd = Path(args.apply_cmd).resolve() if args.apply_cmd else (_find_apply_cmd(repo_root) or None)
  if apply_cmd:
    try:
      return _apply_via_gasket(cbor_bytes ,apply_cmd ,args)
    except Exception as e:
      print(f"error: apply-cmd failed: {e}" ,file=sys.stderr)
      return 2

  inner_py = Path(args.inner_py).resolve() if args.inner_py else (_find_inner_py(repo_root) or None)
  if inner_py:
    try:
      return _apply_via_inner_py(cbor_bytes ,inner_py ,args)
    except Exception as e:
      print(f"error: inner executor failed: {e}" ,file=sys.stderr)
      return 2

  print("error: no apply path found (neither gasket nor inner Python)", file=sys.stderr)
  return 2


if __name__ == "__main__":
  sys.exit(main())
