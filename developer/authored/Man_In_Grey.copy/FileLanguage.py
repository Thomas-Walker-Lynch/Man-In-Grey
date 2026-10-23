# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
FileLanguage - a small command language for writing files, Man-In-Grey's
test language. It is a constrained form of the POSIX file interface.

  open(directory ,name ,mode ,owner ,permission)   produces a symbol for the file
  write(file ,content)                             appends content to the file
  unlink(directory ,name)                          removes a file

The modes of open:

  create         the file must not exist
  replace        an existing file is discarded
  replace_keep   an existing file is kept as <name>.YYYYMMDDTHHMMSSZ

There is no close. Each opened file is written to a temporary file in its
directory, and after the journal's last command every opened file is put in
place, each in one step.

The module has two halves. The composer half is JournalInterface, through
which a composer places commands; it checks every argument when the call is
made, and raises JournalError on a wrong one. The interpreter half checks a
journal received as data, against the constraints of a bespoke interpreter,
and executes it.

Constraints are a map:

  caller            account names allowed to hand a journal to the interpreter
  principal_caller  account names allowed to name a principal other than themselves
  file              entries {directory ,name ,mode ,owner ,permission}: the files
                    the language allows; mode lists the open modes allowed, and
                    "unlink" when unlink is allowed
"""

import os ,pwd ,stat ,time
from pathlib import Path

from Journal import JournalError ,Symbol

NAME = "file"

MODE = ("create" ,"replace" ,"replace_keep")

ARGUMENT = {
  "open": ("directory" ,"name" ,"mode" ,"owner" ,"permission")
  ,"write": ("file" ,"content")
  ,"unlink": ("directory" ,"name")
}


# --------------------------------------------------------------------------------
# argument checks, shared by both halves

def directory_problem(value):
  if not isinstance(value ,str) or not value.startswith("/") or "\x00" in value:
    return "directory is to be an absolute path"
  if os.path.normpath(value) != value:
    return f"directory {value!r} is not in normal form; give {os.path.normpath(value)!r}"
  return None

def name_problem(value):
  if not isinstance(value ,str) or not value or "/" in value or value in ("." ,"..") or "\x00" in value:
    return f"name {value!r} is not a bare file name"
  return None

def permission_value(value):
  "an int 0..0o7777, or a string of 3 or 4 octal digits; None when neither"
  if isinstance(value ,bool):
    return None
  if isinstance(value ,int):
    return value if 0 <= value <= 0o7777 else None
  if isinstance(value ,str) and len(value) in (3 ,4) and all(c in "01234567" for c in value):
    return int(value ,8)
  return None


# --------------------------------------------------------------------------------
# composer half

class JournalInterface:
  """
  The journal interface of the file language. A composer is given one, and
  places commands with its three functions. open returns a Symbol: the file
  the open command will produce when the journal is executed.
  """

  def __init__(self ,journal ,working_dpath):
    self._journal = journal
    self._working_dpath = Path(working_dpath)

  def _directory(self ,directory):
    if not isinstance(directory ,(str ,Path)) or str(directory) == "":
      raise JournalError("directory is to be a path")
    path = Path(directory)
    if not path.is_absolute():
      path = self._working_dpath / path
    return os.path.normpath(str(path))

  def open(self ,directory ,name ,mode ,owner ,permission):
    directory = self._directory(directory)
    problem = name_problem(name)
    if problem: raise JournalError(f"open: {problem}")
    if mode not in MODE:
      raise JournalError(f"open: mode {mode!r} is not one of {', '.join(MODE)}")
    if not isinstance(owner ,str) or not owner:
      raise JournalError("open: owner is to be an account name")
    value = permission_value(permission)
    if value is None:
      raise JournalError(f"open: permission {permission!r} is not an integer 0 to 0o7777 or three or four octal digits")
    return self._journal.place("open" ,{
      "directory": directory ,"name": name ,"mode": mode ,"owner": owner ,"permission": value
    })

  def write(self ,file ,content):
    if not isinstance(file ,Symbol) or self._journal.command_list[file.index].command != "open":
      raise JournalError("write: file is to be the symbol an open returned")
    if isinstance(content ,str):
      content = content.encode("utf-8")
    if not isinstance(content ,(bytes ,bytearray)):
      raise JournalError("write: content is to be text or bytes")
    self._journal.place("write" ,{"file": file ,"content": bytes(content)})

  def unlink(self ,directory ,name):
    directory = self._directory(directory)
    problem = name_problem(name)
    if problem: raise JournalError(f"unlink: {problem}")
    self._journal.place("unlink" ,{"directory": directory ,"name": name})


# --------------------------------------------------------------------------------
# interpreter half: checks, each returning a list of problems

def check_wellformed(data):
  problem_list = []
  for index ,command in enumerate(data["command_list"]):
    name ,argument = command["command"] ,command["argument"]
    if name not in ARGUMENT:
      problem_list.append(f"@{index}: unknown command {name!r}"); continue
    if set(argument) != set(ARGUMENT[name]):
      problem_list.append(f"@{index} {name}: arguments {sorted(argument)}, expected {sorted(ARGUMENT[name])}"); continue
    if name in ("open" ,"unlink"):
      for problem in (directory_problem(argument["directory"]) ,name_problem(argument["name"])):
        if problem: problem_list.append(f"@{index} {name}: {problem}")
    if name == "open":
      if argument["mode"] not in MODE:
        problem_list.append(f"@{index} open: unknown mode {argument['mode']!r}")
      if not isinstance(argument["owner"] ,str) or not argument["owner"]:
        problem_list.append(f"@{index} open: owner is not an account name")
      if permission_value(argument["permission"]) is None or not isinstance(argument["permission"] ,int):
        problem_list.append(f"@{index} open: permission {argument['permission']!r} is not valid")
    if name == "write":
      file = argument["file"]
      if not Symbol.is_data(file) or data["command_list"][file["symbol"]]["command"] != "open":
        problem_list.append(f"@{index} write: file is not the symbol of an open")
      if not isinstance(argument["content"] ,(bytes ,bytearray)):
        problem_list.append(f"@{index} write: content is not bytes")
  return problem_list

def check_constraint(data ,constraint ,caller):
  problem_list = []
  if caller not in constraint.get("caller" ,()):
    return [f"caller {caller!r} is not allowed to hand journals to this interpreter"]
  principal = data.get("principal")
  if principal is not None and principal != caller and caller not in constraint.get("principal_caller" ,()):
    problem_list.append(f"caller {caller!r} is not allowed to name the principal {principal!r}")
  allowed = {}
  for entry in constraint.get("file" ,()):
    allowed[(entry["directory"] ,entry["name"])] = entry
  for index ,command in enumerate(data["command_list"]):
    name ,argument = command["command"] ,command["argument"]
    if name not in ("open" ,"unlink"):
      continue
    where = f"{argument['directory']}/{argument['name']}"
    entry = allowed.get((argument["directory"] ,argument["name"]))
    if entry is None:
      problem_list.append(f"@{index} {name}: {where} is not a file this interpreter allows"); continue
    if name == "unlink":
      if "unlink" not in entry.get("mode" ,()):
        problem_list.append(f"@{index} unlink: {where} is not allowed to be unlinked")
      continue
    if argument["mode"] not in entry.get("mode" ,()):
      problem_list.append(f"@{index} open: {where} is not allowed in mode {argument['mode']}")
    if argument["owner"] != entry.get("owner"):
      problem_list.append(f"@{index} open: {where} is to be owned by {entry.get('owner')!r}, not {argument['owner']!r}")
    if argument["permission"] != permission_value(entry.get("permission")):
      problem_list.append(f"@{index} open: {where} is to have permission {entry.get('permission')}, not {argument['permission']:04o}")
  return problem_list

def check_validity(data):
  problem_list = []
  for index ,command in enumerate(data["command_list"]):
    if command["command"] == "open":
      owner = command["argument"]["owner"]
      try:
        pwd.getpwnam(owner)
      except KeyError:
        problem_list.append(f"@{index} open: no account is named {owner!r}")
  return problem_list

def _regular_or_absent(dirfd ,name):
  "True when absent; False when a regular file; raises OSError otherwise"
  try:
    st = os.lstat(name ,dir_fd=dirfd)
  except FileNotFoundError:
    return True
  if not stat.S_ISREG(st.st_mode):
    raise OSError("it exists and is not a regular file")
  return False

def check_filesystem(data):
  problem_list = []
  seen = set()
  for index ,command in enumerate(data["command_list"]):
    name ,argument = command["command"] ,command["argument"]
    if name not in ("open" ,"unlink"):
      continue
    directory ,file_name = argument["directory"] ,argument["name"]
    where = f"{directory}/{file_name}"
    if (directory ,file_name) in seen:
      problem_list.append(f"@{index} {name}: {where} is named by more than one command"); continue
    seen.add((directory ,file_name))
    if os.path.realpath(directory) != directory:
      problem_list.append(f"@{index} {name}: {directory} passes through a symbolic link"); continue
    try:
      dirfd = os.open(directory ,os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
      problem_list.append(f"@{index} {name}: cannot open directory {directory} ({error.strerror})"); continue
    try:
      absent = _regular_or_absent(dirfd ,file_name)
      if name == "open" and argument["mode"] == "create" and not absent:
        problem_list.append(f"@{index} open: {where} exists, and the mode is create")
    except OSError as error:
      problem_list.append(f"@{index} {name}: {where}: {error}")
    finally:
      os.close(dirfd)
  return problem_list

CHECK = (
  ("wellformed" ,lambda data ,constraint ,caller: check_wellformed(data))
  ,("constraint" ,check_constraint)
  ,("validity" ,lambda data ,constraint ,caller: check_validity(data))
  ,("filesystem" ,lambda data ,constraint ,caller: check_filesystem(data))
)


# --------------------------------------------------------------------------------
# interpreter half: execution

def _backup_name(dirfd ,name):
  stamp = time.strftime("%Y%m%dT%H%M%SZ" ,time.gmtime())
  candidate ,n = f"{name}.{stamp}" ,1
  while True:
    try:
      os.lstat(candidate ,dir_fd=dirfd)
    except FileNotFoundError:
      return candidate
    candidate ,n = f"{name}.{stamp}.{n}" ,n + 1

def execute(data ,log):
  """
  Execute the commands in order, then put each opened file in place. Stops
  at the first error, removing every temporary file not yet put in place.
  Returns 0, or 1 on an error.
  """
  opened = {}   # symbol index -> {dirfd ,fd ,tmp ,argument}
  try:
    for index ,command in enumerate(data["command_list"]):
      name ,argument = command["command"] ,command["argument"]
      if name == "open":
        dirfd = os.open(argument["directory"] ,os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        tmp = f".{argument['name']}.Man_In_Grey.{os.getpid()}.{index}"
        fd = os.open(tmp ,os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW ,0o600 ,dir_fd=dirfd)
        opened[index] = {"dirfd": dirfd ,"fd": fd ,"tmp": tmp ,"argument": argument}
      elif name == "write":
        fd ,view = opened[argument["file"]["symbol"]]["fd"] ,memoryview(argument["content"])
        while view:
          view = view[os.write(fd ,view):]
      elif name == "unlink":
        dirfd = os.open(argument["directory"] ,os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
          if not _regular_or_absent(dirfd ,argument["name"]):
            os.unlink(argument["name"] ,dir_fd=dirfd)
            os.fsync(dirfd)
            log(f"unlinked  {argument['directory']}/{argument['name']}")
        finally:
          os.close(dirfd)

    for index in sorted(opened):
      record = opened[index]
      argument ,dirfd ,fd ,tmp = record["argument"] ,record["dirfd"] ,record["fd"] ,record["tmp"]
      account = pwd.getpwnam(argument["owner"])
      os.fsync(fd)
      os.fchown(fd ,account.pw_uid ,account.pw_gid)
      os.fchmod(fd ,argument["permission"])
      os.fsync(fd)
      os.close(fd); record["fd"] = None
      target = argument["name"]
      where = f"{argument['directory']}/{target}"
      if argument["mode"] == "create":
        os.link(tmp ,target ,src_dir_fd=dirfd ,dst_dir_fd=dirfd ,follow_symlinks=False)
        os.unlink(tmp ,dir_fd=dirfd)
        log(f"created   {where}")
      else:
        kept = None
        if argument["mode"] == "replace_keep" and not _regular_or_absent(dirfd ,target):
          kept = _backup_name(dirfd ,target)
          os.link(target ,kept ,src_dir_fd=dirfd ,dst_dir_fd=dirfd ,follow_symlinks=False)
        os.rename(tmp ,target ,src_dir_fd=dirfd ,dst_dir_fd=dirfd)
        log(f"replaced  {where}" + (f"  (kept as {kept})" if kept else ""))
      record["tmp"] = None
      os.fsync(dirfd)
    return 0
  except OSError as error:
    log(f"error     {error}")
    return 1
  finally:
    for record in opened.values():
      if record.get("fd") is not None:
        os.close(record["fd"])
      if record.get("tmp") is not None:
        try:
          os.unlink(record["tmp"] ,dir_fd=record["dirfd"])
        except OSError:
          pass
      os.close(record["dirfd"])
