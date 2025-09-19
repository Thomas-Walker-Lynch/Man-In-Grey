#!/usr/bin/env -S python3 -B
"""
stage_show_plan.py — run staged configs (UNPRIVILEGED) and print the plan.

Given: a stage root directory.
Does:  loads Stage.py, executes each config, builds a native plan map, summarizes it.
Returns: exit code 0 on success, non-zero on error.
"""
from __future__ import annotations
import sys ,os
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE" ,"1")

from pathlib import Path
import argparse ,importlib.util ,runpy ,socket ,getpass ,time ,hashlib

# ---------- helpers ----------

def _load_stage_module(stage_root_dpath: Path):
  "Given: stage root path. Does: load Stage.py as module 'Stage'. Returns: module."
  mod_fpath = stage_root_dpath/"Stage.py"
  if not mod_fpath.exists():
    raise FileNotFoundError(f"Stage.py not found at {mod_fpath}")
  spec = importlib.util.spec_from_file_location("Stage" ,str(mod_fpath))
  mod = importlib.util.module_from_spec(spec)
  sys.modules["Stage"] = mod
  assert spec and spec.loader
  spec.loader.exec_module(mod)  # type: ignore
  return mod

def _config_rel_fpaths(stage_root_dpath: Path)-> list[Path]:
  "Given: stage root. Does: collect *.py (excluding Stage.py) as relative file paths. Returns: list[Path]."
  rel_fpath_list: list[Path] = []
  for p in stage_root_dpath.rglob("*.py"):
    if p.name == "Stage.py": continue
    if p.is_file():
      rel_fpath_list.append(p.relative_to(stage_root_dpath))
  return sorted(rel_fpath_list ,key=lambda x: x.as_posix())

def _sha256_hex(b: bytes)-> str:
  "Given: bytes. Does: sha256. Returns: hex string."
  return hashlib.sha256(b).hexdigest()

# ---------- main ----------

def main(argv: list[str]|None=None)-> int:
  "Given: CLI. Does: show plan. Returns: exit code."
  ap = argparse.ArgumentParser(prog="stage_show_plan.py"
   ,description="Run staged config scripts and print the resulting plan.")
  ap.add_argument("--stage",default="stage",help="stage directory (default: ./stage)")
  args = ap.parse_args(argv)

  stage_root_dpath = Path(args.stage)
  StageMod = _load_stage_module(stage_root_dpath)
  Stage = StageMod.Stage
  Stage._reset()
  Stage.set_meta(
    planner_user_name=getpass.getuser()
    ,planner_uid_int=os.getuid()
    ,planner_gid_int=os.getgid()
    ,host_name=socket.gethostname()
    ,created_utc_str=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
  )

  for rel_fpath in _config_rel_fpaths(stage_root_dpath):
    Stage._begin(read_rel_fpath=rel_fpath ,stage_root_dpath=stage_root_dpath)
    runpy.run_path(str(stage_root_dpath/rel_fpath) ,run_name="__main__")
    Stage._end()

  plan_map = Stage.plan_object()
  entries_list = plan_map["entries_list"]
  print(f"Plan version: {plan_map['version_int']}")
  print(f"Planner: {plan_map['meta_map'].get('planner_user_name')}@{plan_map['meta_map'].get('host_name')}  "
        f"UID:{plan_map['meta_map'].get('planner_uid_int')} GID:{plan_map['meta_map'].get('planner_gid_int')}")
  print(f"Created: {plan_map['meta_map'].get('created_utc_str')}")
  print(f"Entries: {len(entries_list)}\n")

  for i ,e_map in enumerate(entries_list ,1):
    op = e_map.get("op")
    dst_fpath_str = f"{e_map.get('dst_dpath')}/{e_map.get('dst_fname')}"
    if op == "copy":
      content = e_map.get("content_bytes") or b""
      sz = len(content)
      mode = e_map.get("mode_octal_str") or "????"
      owner = e_map.get("owner_name") or "?"
      h = _sha256_hex(content)
      print(f"{i:02d}. copy     -> {dst_fpath_str}  mode {mode} owner {owner}  bytes {sz} sha256 {h[:16]}…")
    elif op == "displace":
      print(f"{i:02d}. displace -> {dst_fpath_str}")
    elif op == "delete":
      print(f"{i:02d}. delete   -> {dst_fpath_str}")
    else:
      print(f"{i:02d}. ?op?     -> {dst_fpath_str}  ({op})")
  return 0

if __name__ == "__main__":
  sys.exit(main())
