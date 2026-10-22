#!/usr/bin/env -S python3 -B
# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
# developer/tool/sync_engine.py

import os
import sys
import shutil
import filecmp
import stat
import tempfile

def copy_file_atomic(src_abs, dst_abs, mode, dry=False, prefix="sync"):
  if dry:
    print(f"(dry) {prefix}: install -m {oct(mode)[2:]} '{src_abs}' -> '{dst_abs}'")
    return

  parent = os.path.dirname(dst_abs)
  os.makedirs(parent, exist_ok=True)

  fd, tmp_path = tempfile.mkstemp(prefix=".tmp.", dir=parent)
  try:
    with os.fdopen(fd, "wb") as tmpf, open(src_abs, "rb") as sf:
      shutil.copyfileobj(sf, tmpf)
      tmpf.flush()
    os.chmod(tmp_path, mode)
    os.replace(tmp_path, dst_abs)
  except Exception as e:
    if os.path.exists(tmp_path):
      os.unlink(tmp_path)
    raise e

def execute_sync(src_root, dst_root, prefix="sync", dry=False, apply_modes=False, ignore_list=None):
  wrote = False
  if ignore_list is None:
    ignore_list = []

  if not os.path.isdir(src_root):
    print(f"{prefix}: error: Source directory '{src_root}' does not exist.", file=sys.stderr)
    return False

  for root, dirs, files in os.walk(src_root):
    dirs.sort()
    files.sort()
    for fn in files:
      if fn in ignore_list:
        continue
      
      src_abs = os.path.join(root, fn)
      rel = os.path.relpath(src_abs, src_root)
      dst_abs = os.path.join(dst_root, rel)

      st = os.stat(src_abs)
      if apply_modes:
        is_exec = st.st_mode & stat.S_IXUSR
        mode = 0o500 if is_exec else 0o400
      else:
        mode = stat.S_IMODE(st.st_mode)

      if not os.path.exists(dst_abs):
        copy_file_atomic(src_abs, dst_abs, mode, dry, prefix)
        if not dry: print(f"{prefix}: Added   {rel}")
        wrote = True
        continue

      if filecmp.cmp(src_abs, dst_abs, shallow=False):
        continue

      dst_st = os.stat(dst_abs)
      if dst_st.st_mtime > st.st_mtime:
        print(f"{prefix}: error: {rel} skipped. Destination version is newer.")
        continue

      copy_file_atomic(src_abs, dst_abs, mode, dry, prefix)
      if not dry: print(f"{prefix}: Updated {rel}")
      wrote = True

  if not wrote and not dry:
    print(f"{prefix}: (info) nothing new to synchronize from {src_root}")
  
  return wrote
