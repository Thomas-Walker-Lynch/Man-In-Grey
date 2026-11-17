# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Smoke·GuardCheck - the guard's checks of the Smoke instruction language, the tester's smoke test.

It exists to exercise the gate, the guard library and the interpreter
library, and is not for use on a system: its constraints can say where a
file goes, and with what mode, owner and permission, but not what the file
says, and a configuration file's content is what its reader does. It is a
constrained form of the POSIX file interface. The instructions and their
types are in Smoke·Language.py.

The modes of open:

  create         the file must not exist
  replace        an existing file is discarded
  replace-keep   an existing file is kept as <name>.YYYYMMDDTHHMMSSZ

There is no close. Each opened file is written to a temporary file in its
directory, and after the journal's last instruction every opened file is
put in place, each in one step.

This module holds the guard's checks of the language, made after the
well-formed guard has checked the journal against the definition. They are
LIST__CHECK:

  language     the values of the literals: absolute directories in normal
               form, bare file names, a known mode, an account name, a
               permission from 0 to 0o7777, and a channel's content no
               larger than CHANNEL_MAX
  constraint   the predicates at the top of the guard, Smoke·Guard.py:
               is__allowed_account, is__allowed_open and is__allowed_unlink
  validity     every owner is an account
  filesystem   each directory, reached through no symbolic link, and each
               file, named by one instruction only, regular or absent

A file variable can only hold what an open wrote there, since a handle is
never a literal; so the well-formed guard has already ensured every write
writes a file some open opened.

The implementation of the instructions is in Smoke·LibraryInstruction.py.
"""

import os ,pwd ,stat

from Journal import has__control ,clean

MODE = ("create" ,"replace" ,"replace-keep")
CHANNEL_MAX = 4096   # PIPE_BUF: a pipe holds at least this much with no reader


# --------------------------------------------------------------------------------
# value checks

def dirpa__problem(value):
  if not value.startswith("/"):
    return f"directory {clean(repr(value))} is not an absolute path"
  if has__control(value):
    return f"directory {clean(value)} holds a control character"
  if os.path.normpath(value) != value:
    return f"directory {value!r} is not in normal form; give {os.path.normpath(value)!r}"
  return None

def filen__problem(value):
  if not value or "/" in value or value in ("." ,".."):
    return f"file name {clean(repr(value))} is not a bare file name"
  if has__control(value):
    return f"file name {clean(value)} holds a control character"
  return None

def account_name__problem(value):
  if not value or has__control(value):
    return f"owner {clean(repr(value))} is not an account name"
  return None


# --------------------------------------------------------------------------------
# the guard's checks, each given the instructions as Journal.InstructionView

def literal(view):
  "the values of an instruction's arguments, None for a variable"
  return [argument.value for argument in view.list__argument]

def check_language(list__instruction_view ,data ,constraint ,gate_invoking_account):
  list__problem = []
  for view in list__instruction_view:
    name ,value = view.operation ,literal(view)
    if name in ("open" ,"unlink"):
      for problem in (dirpa__problem(value[0]) ,filen__problem(value[1])):
        if problem: list__problem.append(f"@{view.index} {name}: {problem}")
    if name == "open":
      if value[2] not in MODE:
        list__problem.append(f"@{view.index} open: mode {clean(repr(value[2]))} is not one of {', '.join(MODE)}")
      problem = account_name__problem(value[3])
      if problem: list__problem.append(f"@{view.index} open: {problem}")
      if not 0 <= value[4] <= 0o7777:
        list__problem.append(f"@{view.index} open: permission {value[4]} is not from 0 to 0o7777")
    if name == "channel" and len(value[0]) > CHANNEL_MAX:
      list__problem.append(f"@{view.index} channel: {len(value[0])} bytes of content; a channel holds at most {CHANNEL_MAX}")
  return list__problem

def check_constraint(list__instruction_view ,data ,constraint ,gate_invoking_account):
  "constraint is the guard, which holds the predicates; a predicate allows only by answering True"
  if constraint.is__allowed_account(gate_invoking_account) is not True:
    return [f"gate invoking account {clean(repr(gate_invoking_account))} is not allowed to give journals to this gate"]
  list__problem = []
  for view in list__instruction_view:
    name ,value = view.operation ,literal(view)
    if name == "open":
      dirpa__target ,filen__target ,mode ,owner ,permission = value[:5]
      if constraint.is__allowed_open(dirpa__target ,filen__target ,mode ,owner ,permission) is not True:
        list__problem.append(f"@{view.index} open: {dirpa__target}/{filen__target} in mode {mode}, owner {owner}, permission {permission:04o} is not allowed")
    elif name == "unlink":
      dirpa__target ,filen__target = value
      if constraint.is__allowed_unlink(dirpa__target ,filen__target) is not True:
        list__problem.append(f"@{view.index} unlink: {dirpa__target}/{filen__target} is not allowed to be removed")
  return list__problem

def check_validity(list__instruction_view ,data ,constraint ,gate_invoking_account):
  list__problem = []
  for view in list__instruction_view:
    if view.operation == "open":
      owner = literal(view)[3]
      try:
        pwd.getpwnam(owner)
      except KeyError:
        list__problem.append(f"@{view.index} open: no account is named {clean(owner)}")
  return list__problem

def is__absent(dirfd ,name):
  "True when absent; False when a regular file; raises OSError otherwise"
  try:
    st = os.lstat(name ,dir_fd=dirfd)
  except FileNotFoundError:
    return True
  if not stat.S_ISREG(st.st_mode):
    raise OSError("it exists and is not a regular file")
  return False

def check_filesystem(list__instruction_view ,data ,constraint ,gate_invoking_account):
  list__problem = []
  seen = set()
  for view in list__instruction_view:
    name ,value = view.operation ,literal(view)
    if name not in ("open" ,"unlink"):
      continue
    dirpa__target ,filen__target = value[0] ,value[1]
    where = f"{dirpa__target}/{filen__target}"
    if (dirpa__target ,filen__target) in seen:
      list__problem.append(f"@{view.index} {name}: {where} is named by more than one instruction"); continue
    seen.add((dirpa__target ,filen__target))
    if os.path.realpath(dirpa__target) != dirpa__target:
      list__problem.append(f"@{view.index} {name}: {dirpa__target} passes through a symbolic link"); continue
    try:
      dirfd = os.open(dirpa__target ,os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
      list__problem.append(f"@{view.index} {name}: cannot open directory {dirpa__target} ({error.strerror})"); continue
    try:
      absent = is__absent(dirfd ,filen__target)
      if name == "open" and value[2] == "create" and not absent:
        list__problem.append(f"@{view.index} open: {where} exists, and the mode is create")
    except OSError as error:
      list__problem.append(f"@{view.index} {name}: {where}: {error}")
    finally:
      os.close(dirfd)
  return list__problem

LIST__CHECK = (
  ("language" ,check_language)
  ,("constraint" ,check_constraint)
  ,("validity" ,check_validity)
  ,("filesystem" ,check_filesystem)
)
