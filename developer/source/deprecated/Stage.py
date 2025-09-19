#!/usr/bin/env -S python3 -B
"""
Stage.py — planner runtime for staged config programs (UNPRIVILEGED).

Config usage:
  import Stage

  Stage.init(
    write_file_name="."
  , write_dpath="/etc/unbound"
  , write_file_owner_name="root"
  , write_file_permissions=0o644     # or "0644"
  , read_file_contents=b"...bytes..."# bytes preferred; str is utf-8 encoded
  )
  Stage.displace()
  Stage.copy()
  # Stage.delete()

Notes:
  - This module only RECORDS plan steps using native Python values (ints/bytes/str).
  - The outer tool CBOR-encodes the accumulated plan AFTER all configs run.
"""

from __future__ import annotations
import sys ,os
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE" ,"1")

from dataclasses import dataclass ,field
from pathlib import Path
from typing import Any

# ---------- helpers ----------

def _norm_perm(value: int|str)-> tuple[int,str]|None:
  "Given: an int or a 4-char octal string. Does: validate/normalize to (int,'%04o'). Returns: tuple or None."
  if isinstance(value ,int):
    if 0 <= value <= 0o7777:
      return value ,f"{value:04o}"
    return None
  if isinstance(value ,str):
    s = value.strip()
    if len(s)==4 and all(ch in "01234567" for ch in s):
      try:
        v = int(s ,8)
        return v ,s
      except Exception:
        return None
  return None

@dataclass
class _Ctx:
  "Information used by many entries in the plan, plan specific command defaults, i.e. the plan context."
  read_rel_fpath: Path
  stage_root_dpath: Path
  defaults_map: dict[str,Any] = field(default_factory=dict) # this syntax gives each context instance a distinct dictionary.

# ---------- planner singleton ----------

class _Planner:
  "Given: staged config executions. Does: accumulate plan entries. Returns: plan map."
  def __init__(self)-> None:
    self._ctx: _Ctx|None = None
    self._entries_list: list[dict[str,Any]] = []
    self._meta_map: dict[str,Any] = {}

  # ---- framework (called by outer tools) ----
  def _begin(self ,read_rel_fpath: Path ,stage_root_dpath: Path)-> None:
    "Given: a config’s relative file path and stage root. Does: start context. Returns: None."
    self._ctx = _Ctx(read_rel_fpath=read_rel_fpath ,stage_root_dpath=stage_root_dpath)

  def _end(self)-> None:
    "Given: active context. Does: end it. Returns: None."
    self._ctx = None

  def _reset(self)-> None:
    "Given: n/a. Does: clear meta and entries. Returns: None."
    self._entries_list.clear()
    self._meta_map.clear()
    self._ctx = None

  # ---- exported for outer tools ----
  def plan_entries(self)-> list[dict[str,Any]]:
    "Given: n/a. Does: return a shallow copy of current entries. Returns: list[dict]."
    return list(self._entries_list)

  def set_meta(self ,**kv)-> None:
    "Given: keyword meta. Does: merge into meta_map. Returns: None."
    self._meta_map.update(kv)

  def plan_object(self)-> dict[str,Any]:
    "Packages a self-contained plan map ready for CBOR encoding. 
     Given: accumulated meta/entries. Does: freeze a copy and stamp a version. Returns: dict.
     "
    return {
      "version_int": 1
      ,"meta_map": dict(self._meta_map)
      ,"entries_list": list(self._entries_list)
    }

  # ---- config API ----
  def init(
    self
    ,write_file_name: str
    ,write_dpath: str
    ,write_file_owner_name: str
    ,write_file_permissions: int|str
    ,read_file_contents: bytes|str|None=None
  )-> None:
    """
    Given: write filename ('.' → basename of config), destination dir path, owner name,
           permissions (int or '0644'), and optional read content (bytes or str).
    Does:  store per-config defaults used by subsequent Stage.* calls.
    Returns: None.
    """
    if self._ctx is None:
      raise RuntimeError("Stage.init used without active context")
    fname = self._ctx.read_rel_fpath.name if write_file_name == "." else write_file_name
    if isinstance(read_file_contents ,str):
      content_bytes = read_file_contents.encode("utf-8")
    else:
      content_bytes = read_file_contents
    perm_norm = _norm_perm(write_file_permissions)
    if perm_norm is None:
      mode_int ,mode_octal_str = None ,None
    else:
      mode_int ,mode_octal_str = perm_norm
    self._ctx.defaults_map = {
      "dst_fname": fname
      ,"dst_dpath": write_dpath
      ,"owner_name": write_file_owner_name
      ,"mode_int": mode_int
      ,"mode_octal_str": mode_octal_str
      ,"content_bytes": content_bytes
    }

  def _require_defaults(self)-> dict[str,Any]:
    "Given: current ctx. Does: ensure Stage.init ran. Returns: defaults_map."
    if self._ctx is None or not self._ctx.defaults_map:
      raise RuntimeError("Stage.* called before Stage.init in this config")
    return self._ctx.defaults_map

  def displace(self)-> None:
    "Given: defaults. Does: append a displace op. Returns: None."
    d = self._require_defaults()
    self._entries_list.append({
      "op":"displace"
      ,"dst_dpath": d["dst_dpath"]
      ,"dst_fname": d["dst_fname"]
    })

  def copy(self)-> None:
    "Given: defaults. Does: append a copy op. Returns: None."
    d = self._require_defaults()
    self._entries_list.append({
      "op":"copy"
      ,"dst_dpath": d["dst_dpath"]
      ,"dst_fname": d["dst_fname"]
      ,"owner_name": d["owner_name"]
      ,"mode_int": d["mode_int"]
      ,"mode_octal_str": d["mode_octal_str"]
      ,"content_bytes": d["content_bytes"]
    })

  def delete(self)-> None:
    "Given: defaults. Does: append a delete op. Returns: None."
    d = self._require_defaults()
    self._entries_list.append({
      "op":"delete"
      ,"dst_dpath": d["dst_dpath"]
      ,"dst_fname": d["dst_fname"]
    })

# exported singleton
Stage = _Planner()
