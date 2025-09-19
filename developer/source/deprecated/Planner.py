#!/usr/bin/env -S python3 -B
"""
Planner.py — plan builder for staged configuration (UNPRIVILEGED).

Given:  runner-side provenance (PlanProvenance) and optional defaults (WriteFileMeta).
Does:   expose Planner whose command methods (copy/displace/delete) build Command entries,
        resolving arguments with precedence: kwarg > per-call WriteFileMeta > planner default
        (and for filename, fallback to provenance-derived basename). On any argument error,
        the Command is returned with errors and NOT appended to the Journal.
Returns: Journal (model only; dict in/out) via planner.journal().
"""

from __future__ import annotations

# no bytecode anywhere (works under sudo/root shells too)
import sys ,os
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE" ,"1")

from pathlib import Path
import getpass


# ===== Utilities =====

def norm_perm(value: int|str)-> tuple[int,str]|None:
  "Given int or 3/4-char octal string (optionally 0o-prefixed). Does validate/normalize. Returns (int,'%04o') or None."
  if isinstance(value ,int):
    if 0 <= value <= 0o7777:
      return value ,f"{value:04o}"
    return None
  if isinstance(value ,str):
    s = value.strip().lower()
    if s.startswith("0o"):
      try:
        v = int(s ,8)
        return v ,f"{v:04o}"
      except Exception:
        return None
    if len(s) in (3 ,4) and all(ch in "01234567" for ch in s):
      try:
        v = int(s ,8)
        return v ,f"{v:04o}"
      except Exception:
        return None
  return None

def is_abs_dpath(dpath_str: str|None)-> bool:
  "Given path string. Does quick abs dir check. Returns bool."
  return isinstance(dpath_str ,str) and dpath_str.startswith("/") and "\x00" not in dpath_str

def norm_abs_dpath_str(value: str|Path|None)-> str|None:
  "Given str/Path/None. Does normalize absolute dir path string. Returns str or None."
  if value is None: return None
  s = value.as_posix() if isinstance(value ,Path) else str(value)
  return s if is_abs_dpath(s) else None

def norm_fname_or_none(value: str|None)-> str|None:
  "Given candidate filename or None. Does validate bare filename. Returns str or None."
  if value is None: return None
  s = str(value)
  if not s: return None
  if "/" in s or s in ("." ,"..") or "\x00" in s: return None
  return s

def norm_nonempty_owner(value: str|None)-> str|None:
  "Given owner string or None. Does minimally validate (non-empty). Returns str or None."
  if value is None: return None
  s = str(value).strip()
  return s if s else None

def parse_mode(value: int|str|None)-> tuple[int|None ,str|None]:
  "Given int/str/None. Does normalize via norm_perm. Returns (int,'%04o') or (None,None)."
  if value is None: return None ,None
  r = norm_perm(value)
  return r if r is not None else (None ,None)

def norm_content_bytes(value: bytes|str|None)-> bytes|None:
  "Given bytes/str/None. Does normalize to UTF-8 bytes or None. Returns bytes|None."
  if value is None: return None
  if isinstance(value ,bytes): return value
  return value.encode("utf-8")

def norm_dpath_str(value: str|Path|None)-> str|None:
  "Given str/Path/None. Does minimal sanitize; allows relative. Returns str or None."
  if value is None: return None
  s = value.as_posix() if isinstance(value ,Path) else str(value)
  if not s or "\x00" in s: return None
  return s


# ===== Wire-ready model types (no CBOR here) =====

class Command:
  """
  Command — a single planned operation.

  Given name_str ('copy'|'displace'|'delete'), optional arg_dict, optional errors_list.
  Does hold op name, own a fresh arg_dict, collect per-entry errors.
  Returns dictionary via as_dictionary().
  """
  __slots__ = ("name_str" ,"arg_dict" ,"errors_list")

  def __init__(self ,name_str: str ,arg_dict: dict|None=None ,errors_list: list[str]|None=None)-> None:
    self.name_str = name_str
    self.arg_dict = dict(arg_dict) if arg_dict is not None else {}
    self.errors_list = list(errors_list) if errors_list is not None else []

  def add_error(self ,msg_str: str)-> None:
    self.errors_list.append(msg_str)

  def as_dictionary(self)-> dict:
    return {
      "op": self.name_str
      ,"arg_dict": dict(self.arg_dict)
      ,"errors_list": list(self.errors_list)
    }

  def print(self, *, index: int|None=None, file=None)-> None:
    """
    Given: optional index for numbering and optional file-like (defaults to stdout).
    Does:  print a compact, human-readable one-line summary of this command; prints any errors indented below.
    Returns: None.
    """
    if file is None:
      import sys as _sys
      file = _sys.stdout

    op = self.name_str
    ad = self.arg_dict or {}

    # Compose destination path for display
    d = ad.get("write_file_dpath_str") or ""
    f = ad.get("write_file_fname") or ""
    try:
      from pathlib import Path as _Path
      dst = (_Path(d)/f).as_posix() if d and f and "/" not in f else "?"
    except Exception:
      dst = "?"

    # Numbering prefix
    prefix = f"{index:02d}. " if index is not None else ""

    if op == "copy":
      mode  = ad.get("mode_int")
      owner = ad.get("owner_name")
      size  = len(ad.get("content_bytes") or b"")
      line  = f"{prefix}copy     -> {dst}  mode {mode:04o} owner {owner} bytes {size}"
    elif op == "displace":
      line  = f"{prefix}displace -> {dst}"
    elif op == "delete":
      line  = f"{prefix}delete   -> {dst}"
    else:
      line  = f"{prefix}?op?     -> {dst}"

    print(line, file=file)

    # Print any per-entry errors underneath
    for err in self.errors_list:
      print(f"    ! {err}", file=file)


class Journal:
  """
  Journal — ordered list of Command plus provenance metadata (model only; no CBOR).

  Given optional plan_dict in wire shape (for reconstruction).
  Does manage meta, append commands, expose entries, and pack to dict.
  Returns dict via as_dictionary().
  """
  __slots__ = ("meta_dict" ,"command_list")

  def __init__(self ,plan_dict: dict|None=None)-> None:
    self.meta_dict = {}
    self.command_list = []
    if plan_dict is not None:
      self._init_from_dict(plan_dict)

  def _init_from_dict(self ,plan_dict: dict)-> None:
    if not isinstance(plan_dict ,dict):
      raise ValueError("plan_dict must be a dict")
    meta = dict(plan_dict.get("meta_dict") or {})
    entries = plan_dict.get("entries_list") or []
    self.meta_dict.update(meta)
    for e in entries:
      if not isinstance(e ,dict): 
        continue
      op   = e.get("op") or "?"
      args = e.get("arg_dict") or {}
      errs = e.get("errors_list") or []
      self.command_list.append(Command(name_str=op ,arg_dict=dict(args) ,errors_list=list(errs)))

  def set_meta(self ,**kv)-> None:
    self.meta_dict.update(kv)

  def append(self ,cmd: Command)-> None:
    self.command_list.append(cmd)

  def entries_list(self)-> list[dict]:
    return [c.as_dictionary() for c in self.command_list]

  def as_dictionary(self)-> dict:
    return {
      "version_int": 1
      ,"meta_dict": dict(self.meta_dict)
      ,"entries_list": self.entries_list()
    }

  def print(self, *, index_start: int = 1, file=None) -> None:
    """
    Given: optional starting index and optional file-like (defaults to stdout).
    Does:  print each Command on a single line via Command.print(), numbered.
    Returns: None.
    """
    if file is None:
      import sys as _sys
      file = _sys.stdout

    if not self.command_list:
      print("(plan is empty)", file=file)
      return

    for i, cmd in enumerate(self.command_list, start=index_start):
      cmd.print(index=i, file=file)

# ===== Runner-provided provenance =====

# Planner.py
class PlanProvenance:
  """
  Runner-provided, read-only provenance for a single config script.
  """
  __slots__ = ("stage_root_dpath","config_abs_fpath","config_rel_fpath",
               "read_dir_dpath","read_fname","process_user")

  def __init__(self, *, stage_root: Path, config_path: Path):
    import getpass
    self.stage_root_dpath = stage_root.resolve()
    self.config_abs_fpath = config_path.resolve()
    try:
      self.config_rel_fpath = self.config_abs_fpath.relative_to(self.stage_root_dpath)
    except Exception:
      self.config_rel_fpath = Path(self.config_abs_fpath.name)

    self.read_dir_dpath = self.config_abs_fpath.parent

    name = self.config_abs_fpath.name
    if name.endswith(".stage.py"):
      self.read_fname = name[:-len(".stage.py")]
    elif name.endswith(".py"):
      self.read_fname = name[:-3]
    else:
      self.read_fname = name

    # NEW: owner of the StageHand process
    self.process_user = getpass.getuser()

  def print(self, *, file=None) -> None:
    if file is None:
      import sys as _sys
      file = _sys.stdout
    print(f"Stage root:   {self.stage_root_dpath}", file=file)
    print(f"Config (rel): {self.config_rel_fpath.as_posix()}", file=file)
    print(f"Config (abs): {self.config_abs_fpath}", file=file)
    print(f"Read dir:     {self.read_dir_dpath}", file=file)
    print(f"Read fname:   {self.read_fname}", file=file)
    print(f"Process user: {self.process_user}", file=file)   # NEW

# ===== Admin-facing defaults carrier =====

class WriteFileMeta:
  """
  WriteFileMeta — per-call or planner-default write-file attributes.

  Given dpath (abs str/Path) ,fname (bare name or None) ,owner (str)
        ,mode (int|'0644') ,content (bytes|str|None).
  Does normalize into fields (may remain None if absent/invalid).
  Returns object suitable for providing defaults to Planner methods.
  """
  __slots__ = ("dpath_str" ,"fname" ,"owner_name_str" ,"mode_int" ,"mode_octal_str" ,"content_bytes")

  def __init__(self
    ,*
    ,dpath="/"
    ,fname=None            # None → let Planner/provenance choose
    ,owner="root"
    ,mode=0o444
    ,content=None
  ):
    self.dpath_str           = norm_dpath_str(dpath)
    self.fname               = norm_fname_or_none(fname)          # '.' no longer special → None
    self.owner_name_str      = norm_nonempty_owner(owner)         # '.' rejected → None
    self.mode_int, self.mode_octal_str = parse_mode(mode)
    self.content_bytes       = norm_content_bytes(content)

  def print(self, *, label: str | None = None, file=None) -> None:
    """
    Given: optional label and optional file-like (defaults to stdout).
    Does:  print a single-line summary of defaults/overrides.
    Returns: None.
    """
    if file is None:
      import sys as _sys
      file = _sys.stdout

    dpath = self.dpath_str or "?"
    fname = self.fname or "?"
    owner = self.owner_name_str or "?"
    mode_str = f"{self.mode_int:04o}" if isinstance(self.mode_int, int) else (self.mode_octal_str or "?")
    size = len(self.content_bytes) if isinstance(self.content_bytes, (bytes, bytearray)) else 0
    prefix = (label + ": ") if label else ""
    print(f"{prefix}dpath={dpath} fname={fname} owner={owner} mode={mode_str} bytes={size}", file=file)


# ===== Planner =====

class Planner:
  """
  Planner — constructs a Journal of Commands from config scripts.

  Given provenance (PlanProvenance) and optional default WriteFileMeta.
  Does resolve command parameters by precedence: kwarg > per-call WriteFileMeta > planner default,
      with a final filename fallback to provenance basename if still missing.
      On any argument error, returns the Command with errors and DOES NOT append it to Journal.
  Returns live Journal via journal().
  """
  __slots__ = ("_prov" ,"_defaults" ,"_journal")

  def __init__(self ,provenance: PlanProvenance ,defaults: WriteFileMeta|None=None)-> None:
    self._prov = provenance
    self._defaults = defaults if defaults is not None else WriteFileMeta(
      dpath="/"
      ,fname=provenance.read_fname
      ,owner="root"
      ,mode=0o444
      ,content=None
    )
    self._journal = Journal()
    self._journal.set_meta(
      stage_root_dpath_str=str(self._prov.stage_root_dpath)
      ,config_rel_fpath_str=self._prov.config_rel_fpath.as_posix()
    )

  # --- defaults management / access ---

  # in Planner.py, inside class Planner
  def set_provenance(self, prov: PlanProvenance) -> None:
    """Switch the current provenance used for fallbacks & per-command provenance tagging."""
    self._prov = prov

  def set_defaults(self ,defaults: WriteFileMeta)-> None:
    "Given WriteFileMeta. Does replace planner defaults. Returns None."
    self._defaults = defaults

  def defaults(self)-> WriteFileMeta:
    "Given n/a. Does return current WriteFileMeta defaults. Returns WriteFileMeta."
    return self._defaults

  def journal(self)-> Journal:
    "Given n/a.  Returns Journal reference (live, still being modified here)."
    return self._journal

  # --- resolution helpers ---

  def _pick(self ,kw ,meta_attr ,default_attr):
    "Given three sources. Does pick first non-None. Returns value or None."
    return kw if kw is not None else (meta_attr if meta_attr is not None else default_attr)

  def _resolve_write_file(self, wfm, dpath, fname) -> tuple[str|None, str|None]:
    dpath_str = norm_dpath_str(dpath) if dpath is not None else None
    fname     = norm_fname_or_none(fname) if fname is not None else None

    dpath_val = self._pick(dpath_str, (wfm.dpath_str if wfm else None), self._defaults.dpath_str)
    fname_val = self._pick(fname,     (wfm.fname     if wfm else None), self._defaults.fname)

    # final fallback for filename: derive from config name
    if fname_val is None:
      fname_val = self._prov.read_fname

    # anchor relative dpaths against the config’s directory
    if dpath_val is not None and not is_abs_dpath(dpath_val):
      dpath_val = (self._prov.read_dir_dpath / dpath_val).as_posix()

    return dpath_val, fname_val

  def _resolve_owner_mode_content(self
    ,wfm: WriteFileMeta|None
    ,owner: str|None
    ,mode: int|str|None
    ,content: bytes|str|None
  )-> tuple[str|None ,tuple[int|None ,str|None] ,bytes|None]:
    owner_norm = norm_nonempty_owner(owner) if owner is not None else None
    mode_norm  = parse_mode(mode) if mode is not None else (None ,None)
    content_b  = norm_content_bytes(content) if content is not None else None

    owner_v = self._pick(owner_norm, (wfm.owner_name_str if wfm else None), self._defaults.owner_name_str)
    mode_v  = (mode_norm if mode_norm != (None ,None) else
               ((wfm.mode_int ,wfm.mode_octal_str) if wfm else (self._defaults.mode_int ,self._defaults.mode_octal_str)))
    content_v = self._pick(content_b ,(wfm.content_bytes if wfm else None) ,self._defaults.content_bytes)
    return owner_v ,mode_v ,content_v

  def print(self, *, show_journal: bool = True, file=None) -> None:
    """
    Given: flags (show_journal) and optional file-like (defaults to stdout).
    Does:  print provenance, defaults, and optionally the journal via delegation.
    Returns: None.
    """
    if file is None:
      import sys as _sys
      file = _sys.stdout

    print("== Provenance ==", file=file)
    self._prov.print(file=file)

    print("\n== Defaults ==", file=file)
    self._defaults.print(label="defaults", file=file)

    if show_journal:
      entries = getattr(self._journal, "command_list", [])
      n_total = len(entries)
      n_copy = sum(1 for c in entries if getattr(c, "name_str", None) == "copy")
      n_disp = sum(1 for c in entries if getattr(c, "name_str", None) == "displace")
      n_del  = sum(1 for c in entries if getattr(c, "name_str", None) == "delete")

      print("\n== Journal ==", file=file)
      print(f"entries: {n_total}  copy:{n_copy}  displace:{n_disp}  delete:{n_del}", file=file)
      if n_total:
        self._journal.print(index_start=1, file=file)
      else:
        print("(plan is empty)", file=file)

  # --- Command builders (first arg may be WriteFileMeta) ---

  def copy(self
    ,wfm: WriteFileMeta|None=None
    ,*
    ,write_file_dpath: str|Path|None=None
    ,write_file_fname: str|None=None
    ,owner: str|None=None
    ,mode: int|str|None=None
    ,content: bytes|str|None=None
  )-> Command:
    """
    Given optional WriteFileMeta plus keyword overrides.
    Does build a 'copy' command; on any argument error the command is returned with errors and NOT appended.
    Returns Command.
    """
    cmd = Command("copy")
    dpath ,fname = self._resolve_write_file(wfm ,write_file_dpath ,write_file_fname)
    owner_v ,(mode_int ,mode_oct) ,content_b = self._resolve_owner_mode_content(wfm ,owner ,mode ,content)

    # well-formed checks
    if not is_abs_dpath(dpath):            cmd.add_error("write_file_dpath must be absolute")
    if norm_fname_or_none(fname) is None:  cmd.add_error("write_file_fname must be a bare filename")
    if not owner_v:                        cmd.add_error("owner must be non-empty")
    if (mode_int ,mode_oct) == (None ,None):
      cmd.add_error("mode must be int <= 0o7777 or 3/4-digit octal string")
    if content_b is None:
      cmd.add_error("content is required for copy() (bytes or str)")

    cmd.arg_dict.update({
      "write_file_dpath_str": dpath,
      "write_file_fname": fname,           # was write_file_fname
      "owner_name": owner_v,               # was owner_name_str
      "mode_int": mode_int,
      "mode_octal_str": mode_oct,
      "content_bytes": content_b,
      "provenance_config_rel_fpath_str": self._prov.config_rel_fpath.as_posix(),
    })

    if not cmd.errors_list:
      self._journal.append(cmd)
    return cmd

  def displace(self
    ,wfm: WriteFileMeta|None=None
    ,*
    ,write_file_dpath: str|Path|None=None
    ,write_file_fname: str|None=None
  )-> Command:
    "Given optional WriteFileMeta plus overrides. Does build 'displace' entry or return errors. Returns Command."
    cmd = Command("displace")
    dpath ,fname = self._resolve_write_file(wfm ,write_file_dpath ,write_file_fname)
    if not is_abs_dpath(dpath):            cmd.add_error("write_file_dpath must be absolute")
    if norm_fname_or_none(fname) is None:  cmd.add_error("write_file_fname must be a bare filename")
    cmd.arg_dict.update({
      "write_file_dpath_str": dpath,
      "write_file_fname": fname,
    })
    if not cmd.errors_list:
      self._journal.append(cmd)
    return cmd

  def delete(self
    ,wfm: WriteFileMeta|None=None
    ,*
    ,write_file_dpath: str|Path|None=None
    ,write_file_fname: str|None=None
  )-> Command:
    "Given optional WriteFileMeta plus overrides. Does build 'delete' entry or return errors. Returns Command."
    cmd = Command("delete")
    dpath ,fname = self._resolve_write_file(wfm ,write_file_dpath ,write_file_fname)
    if not is_abs_dpath(dpath):            cmd.add_error("write_file_dpath must be absolute")
    if norm_fname_or_none(fname) is None:  cmd.add_error("write_file_fname must be a bare filename")
    cmd.arg_dict.update({
      "write_file_dpath_str": dpath,
      "write_file_fname": fname,
    })
    if not cmd.errors_list:
      self._journal.append(cmd)
    return cmd


  
