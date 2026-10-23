#!/usr/bin/env -S python3 -B
# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
journal_interpreter_file

The bespoke journal interpreter for the file command language, started by
its gate, Man_In_Grey_file_gate, with the journal on standard input.

Its constraints are the file constraints_file.json beside it. When it runs
privileged, that file, this program, and the modules it loads are to be
owned by root and writable by no one else, or it refuses to run. When it runs
unprivileged, through a gate that was not blessed, the caller can give other
constraints with --constraints, since nothing then runs with more than the
caller's own rights.

Usage: journal_interpreter_file [--constraints <file>] [--print] [--stop-after <check>]
  --constraints <file>   constraints to use in place of constraints_file.json; unprivileged only
  --print                print the journal as decoded
  --stop-after <check>   stop after decode, wellformed, constraint, validity or filesystem
"""

import sys ,os
sys.dont_write_bytecode = True

import json ,pwd ,stat
from pathlib import Path

HERE_DPATH = Path(__file__).resolve().parent
CONSTRAINT_FILE = HERE_DPATH / "constraints_file.json"
MODULE = ("Journal.py" ,"FileLanguage.py" ,"journal_interpreter.py" ,"journal_interpreter_file.py")


def privileged():
  return os.geteuid() != os.getuid() or os.getegid() != os.getgid()

def owned_by_root_problem(path):
  try:
    st = os.lstat(path)
  except OSError as error:
    return f"{path}: {error.strerror}"
  if st.st_uid != 0:
    return f"{path} is not owned by root"
  if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
    return f"{path} is writable by an account other than root"
  return None

# Running privileged, every file this program loads is checked before any of
# it is imported: a module runs code when it is imported.
if privileged():
  for each in [HERE_DPATH ,CONSTRAINT_FILE] + [HERE_DPATH / m for m in MODULE]:
    problem = owned_by_root_problem(each)
    if problem:
      print(f"error: refusing to run privileged: {problem}" ,file=sys.stderr)
      sys.exit(2)

import journal_interpreter
import FileLanguage


def load_constraint(given):
  if given is not None:
    if privileged():
      raise RuntimeError("--constraints is refused when running privileged")
    path = Path(given)
  else:
    path = CONSTRAINT_FILE
  with open(path ,encoding="utf-8") as f:
    return json.load(f)

def CLI(argv=None):
  argv = sys.argv[1:] if argv is None else argv
  given ,stop_after ,print_journal = None ,None ,False
  i = 0
  while i < len(argv):
    word = argv[i]
    if word == "--constraints" and i + 1 < len(argv):
      given = argv[i + 1]; i += 2
    elif word == "--stop-after" and i + 1 < len(argv) and argv[i + 1] in journal_interpreter.STOP:
      stop_after = argv[i + 1]; i += 2
    elif word == "--print":
      print_journal = True; i += 1
    else:
      print(f"error: unknown argument {word!r}" ,file=sys.stderr)
      return 2
  try:
    constraint = load_constraint(given)
  except (OSError ,ValueError ,RuntimeError) as error:
    print(f"error: constraints: {error}" ,file=sys.stderr)
    return 2
  caller = pwd.getpwuid(os.getuid()).pw_name
  journal_bytes = sys.stdin.buffer.read()
  return journal_interpreter.interpret(
    journal_bytes ,FileLanguage ,constraint ,caller
    ,stop_after=stop_after ,print_journal=print_journal
  )


if __name__ == "__main__":
  sys.exit(CLI())
