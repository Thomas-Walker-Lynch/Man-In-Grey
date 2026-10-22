#!/usr/bin/env -S python3 -B
"""
executor_inner.py — Man_In_Gray phase-2 inner executor

- Reads a CBOR plan file (--plan)
- Decodes to Journal (via Planner.py model)
- Optional checkpoints:
    wellformed → sanity-1 → validity → sanity-2 → execute
- Default behavior (no stop flags): apply the journal
"""

from __future__ import annotations

# no bytecode anywhere
import sys ,os
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE" ,"1")

from pathlib import Path
import argparse
import pwd
import stat as _stat

# Journal model comes from the same directory's Planner.py
from Planner import (
  Journal,
)

# -- helpers --

def _realpath(p: str|Path)-> Path:
  "Resolve as much as possible without requiring target leaf to exist."
  return Path(os.path.realpath(str(p)))

def _is_under(child: Path ,root: Path)-> bool:
  "True if child is the same as or within root (after realpath)."
  try:
    child_r = _realpath(child)
    root_r  = _realpath(root)
    # Python <3.9 compat for is_relative_to:
    child_parts = child_r.as_posix().rstrip("/") + "/"
    root_parts  = root_r.as_posix().rstrip("/") + "/"
    return child_parts.startswith(root_parts)
  except Exception:
    return False

# --- CBOR load ---

def _journal_from_cbor_bytes(data: bytes)-> Journal:
  try:
    import cbor2
  except Exception as e:
    raise RuntimeError(f"cbor2 is required: {e}")
  obj = cbor2.loads(data)
  if not isinstance(obj ,dict):
    raise ValueError("CBOR root must be a dict")
  return Journal(plan_dict=obj)

# --- pretty helpers ---

def _dst_from(ad: dict)-> str:
  d = ad.get("write_file_dpath_str") or "?"
  f = ad.get("write_file_fname") or "?"
  try:
    from pathlib import Path as _P
    if isinstance(d ,str) and isinstance(f ,str) and "/" not in f:
      return (_P(d)/f).as_posix()
  except Exception:
    pass
  return f"{d}/{f}"

def _mode_from_entry(ad: dict)-> int:
  m = ad.get("mode_int")
  if isinstance(m ,int): return m
  s = ad.get("mode_octal_str")
  if isinstance(s ,str):
    try:
      return int(s ,8)
    except Exception:
      pass
  raise ValueError("invalid mode")

# --- Phase: wellformed (schema/shape) ---

def check_wellformed(journal: Journal)-> list[str]:
  errs: list[str] = []
  for i ,cmd in enumerate(journal.command_list ,start=1):
    op = getattr(cmd ,"name_str" ,None)
    ad = getattr(cmd ,"arg_dict" ,None)
    if op not in {"copy" ,"displace" ,"delete"}:
      errs.append(f"[{i}] unknown op: {op!r}")
      continue
    if not isinstance(ad ,dict):
      errs.append(f"[{i}] arg_dict missing")
      continue
    d = ad.get("write_file_dpath_str")
    f = ad.get("write_file_fname")
    if not (isinstance(d ,str) and d.startswith("/")):
      errs.append(f"[{i}] write_file_dpath_str must be absolute: {d!r}")
    if not (isinstance(f ,str) and "/" not in f and f not in {"." ,""}):
      errs.append(f"[{i}] write_file_fname must be a bare filename: {f!r}")
    if op == "copy":
      if "owner_name" not in ad:
        errs.append(f"[{i}] copy: owner_name missing")
      if "content_bytes" not in ad:
        errs.append(f"[{i}] copy: content_bytes missing")
      if "mode_int" not in ad and "mode_octal_str" not in ad:
        errs.append(f"[{i}] copy: mode missing")
  return errs

# --- Phase: sanity-1 (cheap static sanity) ---

def check_sanity_1(journal: Journal ,allowed_roots: list[Path])-> list[str]:
  """
  Scope fence: every destination directory must be under at least one allowed root.
  Default allowed roots = [/etc, cwd_of_inner].
  """
  errs: list[str] = []
  allowed_str = ", ".join(r.as_posix() for r in allowed_roots)
  for i ,cmd in enumerate(journal.command_list ,start=1):
    ad = cmd.arg_dict
    d  = ad.get("write_file_dpath_str")
    if not isinstance(d ,str):
      # wellformed will report it; skip here
      continue
    d_real = _realpath(d)
    if not any(_is_under(d_real ,root) for root in allowed_roots):
      errs.append(f"[{i}] dst dir outside allowed roots: {d_real.as_posix()}  (allowed: {allowed_str})")
  return errs

# --- Phase: validity (system lookups) ---

def check_validity(journal: Journal)-> list[str]:
  errs: list[str] = []
  for i ,cmd in enumerate(journal.command_list ,start=1):
    ad = cmd.arg_dict
    if cmd.name_str == "copy":
      owner = ad.get("owner_name")
      try:
        pwd.getpwnam(owner)
      except Exception:
        errs.append(f"[{i}] unknown owner_name: {owner!r} (dst={_dst_from(ad)})")
      try:
        _ = _mode_from_entry(ad)
      except Exception as e:
        errs.append(f"[{i}] bad mode: {e} (dst={_dst_from(ad)})")
      cb = ad.get("content_bytes")
      if not isinstance(cb ,(bytes ,bytearray)):
        errs.append(f"[{i}] content_bytes not bytes-like (dst={_dst_from(ad)})")
  return errs

# --- Phase: sanity-2 (filesystem checks, no mutation) ---

def _safe_open_dir(dpath: str)-> int:
  fd = os.open(dpath ,os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
  st = os.fstat(fd)
  if not _stat.S_ISDIR(st.st_mode):
    os.close(fd) ; raise OSError("not a directory")
  return fd




def check_sanity_2(journal: Journal)-> list[str]:
  errs: list[str] = []
  opened: dict[str ,int] = {}
  try:
    # ensure destination directories are openable (and not symlinked dirs)
    for i ,cmd in enumerate(journal.command_list ,start=1):
      d = cmd.arg_dict.get("write_file_dpath_str")
      if not isinstance(d ,str):   # already flagged in wellformed
        continue
      if d in opened:
        continue
      try:
        opened[d] = _safe_open_dir(d)
      except Exception as e:
        errs.append(f"[{i}] cannot open destination dir: {d} ({e})")

    # detect multiple writes to same target without a reset (displace/delete)
    last_action: dict[tuple[str, str], str] = {}
    for i, cmd in enumerate(journal.command_list, start=1):
      ad = cmd.arg_dict
      key = (ad.get("write_file_dpath_str"), ad.get("write_file_fname"))
      op = cmd.name_str
      if op == "copy":
        if last_action.get(key) == "copy":
          errs.append(f"[{i}] multiple writes to same target without prior displace/delete: {_dst_from(ad)}")
        last_action[key] = "copy"
      elif op in {"displace", "delete"}:
        last_action[key] = op

  finally:
    for fd in opened.values():
      try:
        os.close(fd)
      except Exception:
        pass
  return errs

# --- Execute (mutation) ---

def _fsync_dirfd(dirfd: int)-> None:
  try:
    os.fsync(dirfd)
  except Exception:
    pass

def _exists_regular_nosymlink_at(dirfd: int ,fname: str)-> bool:
  try:
    st = os.lstat(fname ,dir_fd=dirfd)
  except FileNotFoundError:
    return False
  if _stat.S_ISLNK(st.st_mode): raise OSError("target is a symlink")
  if not _stat.S_ISREG(st.st_mode): raise OSError("target not a regular file")
  return True

def _apply_displace(d: str ,f: str)-> None:
  dirfd = _safe_open_dir(d)
  try:
    if not _exists_regular_nosymlink_at(dirfd ,f):
      return
    import time as _time
    ts = _time.strftime("%Y%m%dT%H%M%SZ" ,_time.gmtime())
    bak = f"{f}.{ts}"
    os.rename(f ,bak ,src_dir_fd=dirfd ,dst_dir_fd=dirfd)
    _fsync_dirfd(dirfd)
  finally:
    os.close(dirfd)

def _apply_copy(d: str ,f: str ,owner: str ,mode_int: int ,content: bytes)-> None:
  pw = pwd.getpwnam(owner)
  uid ,gid = pw.pw_uid ,pw.pw_gid
  dirfd = _safe_open_dir(d)
  try:
    tmp = f".{f}.mig.tmp.{os.getpid()}"
    tfd = os.open(tmp ,os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW ,0o600 ,dir_fd=dirfd)
    try:
      mv = memoryview(content)
      off = 0
      while off < len(mv):
        n = os.write(tfd ,mv[off:])
        if n <= 0: raise OSError("short write")
        off += n
      os.fsync(tfd)
      os.fchown(tfd ,uid ,gid)
      os.fchmod(tfd ,mode_int)
      os.fsync(tfd)
    finally:
      os.close(tfd)
    os.rename(tmp ,f ,src_dir_fd=dirfd ,dst_dir_fd=dirfd)
    _fsync_dirfd(dirfd)
  finally:
    os.close(dirfd)

def _apply_delete(d: str ,f: str)-> None:
  dirfd = _safe_open_dir(d)
  try:
    if not _exists_regular_nosymlink_at(dirfd ,f):
      return
    os.unlink(f ,dir_fd=dirfd)
    _fsync_dirfd(dirfd)
  finally:
    os.close(dirfd)

def apply_journal(journal: Journal)-> int:
  errs = 0
  for idx ,entry in enumerate(journal.command_list ,start=1):
    op = getattr(entry ,"name_str" ,"?")
    ad = getattr(entry ,"arg_dict" ,{}) or {}
    try:
      d = ad["write_file_dpath_str"]
      f = ad["write_file_fname"]
      if not (isinstance(d ,str) and d.startswith("/") and isinstance(f ,str) and "/" not in f):
        raise ValueError("bad path or filename")
      if op == "displace":
        _apply_displace(d ,f)
      elif op == "copy":
        owner = ad["owner_name"]
        mode  = _mode_from_entry(ad)
        content = ad["content_bytes"]
        if not isinstance(content ,(bytes ,bytearray)): raise ValueError("content_bytes missing")
        _apply_copy(d ,f ,owner ,mode ,bytes(content))
      elif op == "delete":
        _apply_delete(d ,f)
      else:
        raise ValueError(f"unknown op: {op}")
    except Exception as e:
      errs += 1
      print(f"apply error [{idx} {op}] {_dst_from(ad)}: {e}" ,file=sys.stderr)
  return 0 if errs == 0 else 1

# --- Orchestration ---

def _phase_gate(name: str ,errors: list[str] ,then_stop: bool)-> bool:
  if errors:
    print(f"{name}: {len(errors)} issue(s)")
    for e in errors:
      print(f"  ! {e}")
    return True
  if then_stop:
    print(f"{name}: OK")
    return True
  return False

def executor_inner(
  journal: Journal
  ,*
  ,phase_2_print: bool=False
  ,phase_2_then_stop: bool=False
  ,phase_2_wellformed_then_stop: bool=False
  ,phase_2_sanity1_then_stop: bool=False
  ,phase_2_validity_then_stop: bool=False
  ,phase_2_sanity2_then_stop: bool=False
  ,allowed_roots: list[Path]|None=None
)-> int:
  """
  Core pipeline for the inner executor. Returns a process-style exit code.
  """
  if phase_2_print:
    journal.print()
  if phase_2_then_stop:
    return 0

  roots = allowed_roots or [Path("/etc").resolve() ,Path.cwd().resolve()]

  wf = check_wellformed(journal)
  if _phase_gate("wellformed" ,wf ,phase_2_wellformed_then_stop):
    return 1 if wf else 0 if phase_2_wellformed_then_stop else 0

  s1 = check_sanity_1(journal ,roots)
  if _phase_gate("sanity-1" ,s1 ,phase_2_sanity1_then_stop):
    return 1 if s1 else 0 if phase_2_sanity1_then_stop else 0

  v  = check_validity(journal)
  if _phase_gate("validity" ,v ,phase_2_validity_then_stop):
    return 1 if v else 0 if phase_2_validity_then_stop else 0

  s2 = check_sanity_2(journal)
  if _phase_gate("sanity-2" ,s2 ,phase_2_sanity2_then_stop):
    return 1 if s2 else 0 if phase_2_sanity2_then_stop else 0

  return apply_journal(journal)

# --- CLI wrapper ---

# --- new worker --------------------------------------------------------------

def run_executor_inner(
  *
  ,plan_bytes: bytes
  ,phase2_print: bool
  ,phase2_then_stop: bool
  ,phase2_wellformed_then_stop: bool
  ,phase2_sanity1_then_stop: bool
  ,phase2_validity_then_stop: bool
  ,phase2_sanity2_then_stop: bool
)-> int:
  try:
    journal = _journal_from_cbor_bytes(plan_bytes)
  except Exception as e:
    print(f"error: failed to decode CBOR: {e}" ,file=sys.stderr)
    return 2

  if phase2_print:
    journal.print()
  if phase2_then_stop:
    return 0

  allowed_roots = [Path("/etc").resolve() ,Path.cwd().resolve()]

  wf = check_wellformed(journal)
  if _phase_gate("wellformed" ,wf ,phase2_wellformed_then_stop): return 1 if wf else 0 if phase2_wellformed_then_stop else 0

  s1 = check_sanity_1(journal ,allowed_roots)
  if _phase_gate("sanity-1" ,s1 ,phase2_sanity1_then_stop): return 1 if s1 else 0 if phase2_sanity1_then_stop else 0

  v  = check_validity(journal)
  if _phase_gate("validity" ,v ,phase2_validity_then_stop): return 1 if v else 0 if phase2_validity_then_stop else 0

  s2 = check_sanity_2(journal)
  if _phase_gate("sanity-2" ,s2 ,phase2_sanity2_then_stop): return 1 if s2 else 0 if phase2_sanity2_then_stop else 0

  return apply_journal(journal)

# --- main stays a thin arg wrapper ------------------------------------------

# --- plan input helpers -------------------------------------------------------

def _read_fd_all(fd: int) -> bytes:
  "Read all bytes from an already-open file descriptor without closing it."
  chunks: list[bytes] = []
  while True:
    try:
      b = os.read(fd, 65536)
    except InterruptedError:
      continue
    if not b:
      break
    chunks.append(b)
  return b"".join(chunks)

def _read_plan_bytes_from_args(args) -> bytes:
  """
  Input priority:
    1) --plan-fd <n>  (gasket path; do not close fd)
    2) --plan -       (stdin)
    3) --plan <file>  (read from filesystem)
  """
  if getattr(args, "plan_fd", -1) is not None and args.plan_fd >= 0:
    return _read_fd_all(args.plan_fd)
  if args.plan in ("", "-"):
    return sys.stdin.buffer.read()
  return Path(args.plan).read_bytes()

def main(argv: list[str] | None = None) -> int:
  ap = argparse.ArgumentParser(
    prog="executor_inner.py",
    description="Man_In_Grey inner executor (decode → validate → apply)"
  )

  # Single --plan plus a hidden --plan-fd used by the gasket
  ap.add_argument(
    "--plan",
    default="-",
    help="path to CBOR plan file or '-' for stdin"
  )
  ap.add_argument(
    "--plan-fd",
    type=int,
    default=-1,
    help=argparse.SUPPRESS
  )

  # phase-2 gates (same semantics as before)
  ap.add_argument("--phase-2-print", action="store_true", help="print decoded journal")
  ap.add_argument("--phase-2-then-stop", action="store_true", help="stop after print (no apply)")
  ap.add_argument("--phase-2-wellformed-then-stop", action="store_true", help="stop after wellformed checks")
  ap.add_argument("--phase-2-sanity1-then-stop",   action="store_true", help="stop after sanity-1 checks")
  ap.add_argument("--phase-2-validity-then-stop",  action="store_true", help="stop after validity checks")
  ap.add_argument("--phase-2-sanity2-then-stop",   action="store_true", help="stop after sanity-2 checks")

  args = ap.parse_args(argv)

  # Read plan bytes from fd/stdin/file
  try:
    data = _read_plan_bytes_from_args(args)
  except Exception as e:
    print(f"error: failed to read plan: {e}", file=sys.stderr)
    return 2

  # Decode CBOR → Journal
  try:
    journal = _journal_from_cbor_bytes(data)
  except Exception as e:
    print(f"error: failed to decode CBOR: {e}", file=sys.stderr)
    return 2

  # Run the pipeline
  return executor_inner(
    journal,
    phase_2_print=args.phase_2_print,
    phase_2_then_stop=args.phase_2_then_stop,
    phase_2_wellformed_then_stop=args.phase_2_wellformed_then_stop,
    phase_2_sanity1_then_stop=args.phase_2_sanity1_then_stop,
    phase_2_validity_then_stop=args.phase_2_validity_then_stop,
    phase_2_sanity2_then_stop=args.phase_2_sanity2_then_stop,
  )

if __name__ == "__main__":
  sys.exit(main())


