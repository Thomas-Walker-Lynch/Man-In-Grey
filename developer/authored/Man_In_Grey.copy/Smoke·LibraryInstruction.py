# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Smoke·LibraryInstruction - the implementation of the Smoke instructions.

The interpreter makes one LibraryInstruction for each journal and calls its
functions, one for each operation specifier of the definition,
Smoke·Language.py, given each instruction's arguments by position.
Each opened file is written to a temporary file in its directory, and
finish() puts every opened file in place, each in one step.
"""

import os ,pwd ,time

from Smoke·GuardCheck import is__absent


# --------------------------------------------------------------------------------
# the interpreter's side

def _backup_name(dirfd ,name):
  stamp = time.strftime("%Y%m%dT%H%M%SZ" ,time.gmtime())
  candidate ,n = f"{name}.{stamp}" ,1
  while True:
    try:
      os.lstat(candidate ,dir_fd=dirfd)
    except FileNotFoundError:
      return candidate
    candidate ,n = f"{name}.{stamp}.{n}" ,n + 1

class LibraryInstruction:
  """
  The instructions of one journal. open makes a temporary file in its directory and
  writes the file's handle, a number standing for the open file, to its box;
  write appends to the file the handle stands for; finish() puts every opened
  file in place, each in one step; release() closes what is open and removes
  every temporary file not put in place. The Smoke language needs nothing
  from its guard's constraints to execute.
  """

  def __init__(self ,constraint ,gate_invoking_account ,log):
    self._log = log
    self._opened = []   # by handle: {dirfd ,fd ,tmp ,dirpa ,name ,mode ,owner ,permission}
    self._count_of__unlink = 0

  def open(self ,dirpa__target ,filen__target ,mode ,account_name ,permission ,file):
    handle = len(self._opened)
    dirfd = os.open(dirpa__target ,os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    record = {"dirfd": dirfd ,"fd": None ,"tmp": None ,"dirpa": dirpa__target ,"name": filen__target
              ,"mode": mode ,"owner": account_name ,"permission": permission}
    self._opened.append(record)
    tmp = f".{filen__target}.Man-In-Grey.{os.getpid()}.{handle}"
    record["fd"] = os.open(tmp ,os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW ,0o600 ,dir_fd=dirfd)
    record["tmp"] = tmp
    file.append(handle)

  def write(self ,file ,content):
    fd ,view = self._opened[file[0]]["fd"] ,memoryview(content)
    while view:
      view = view[os.write(fd ,view):]

  def unlink(self ,dirpa__target ,filen__target):
    dirfd = os.open(dirpa__target ,os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
      if not is__absent(dirfd ,filen__target):
        os.unlink(filen__target ,dir_fd=dirfd)
        os.fsync(dirfd)
        self._log("unlinked" ,f"{dirpa__target}/{filen__target}")
    finally:
      os.close(dirfd)
    self._count_of__unlink += 1

  def summary(self ,summary):
    summary.append({"count_of__open": len(self._opened) ,"count_of__unlink": self._count_of__unlink})

  def channel(self ,content ,channel):
    """
    A pipe holding content, its writing end closed; the reading end is
    written to channel. The guard keeps content within what a pipe holds
    with no reader, so the write cannot wait. The reading end is not closed
    here: when the journal's result holds it, Interpreter.write_result
    sends it to the gate and closes it.
    """
    fd__read ,fd__write = os.pipe()
    try:
      view = memoryview(content)
      while view:
        view = view[os.write(fd__write ,view):]
    finally:
      os.close(fd__write)
    channel.append(fd__read)

  def finish(self):
    for record in self._opened:
      dirfd ,fd ,tmp ,filen__target = record["dirfd"] ,record["fd"] ,record["tmp"] ,record["name"]
      where = f"{record['dirpa']}/{filen__target}"
      account = pwd.getpwnam(record["owner"])
      os.fsync(fd)
      # Only root can give a file away. Any other interpreter account makes
      # files it already owns, so the owner is changed only when it differs.
      st = os.fstat(fd)
      if (st.st_uid ,st.st_gid) != (account.pw_uid ,account.pw_gid):
        try:
          os.fchown(fd ,account.pw_uid ,account.pw_gid)
        except OSError as error:
          raise OSError(error.errno ,f"{where}: cannot give it the owner {record['owner']} and that account's group: {error.strerror}")
      os.fchmod(fd ,record["permission"])
      os.fsync(fd)
      os.close(fd); record["fd"] = None
      if record["mode"] == "create":
        os.link(tmp ,filen__target ,src_dir_fd=dirfd ,dst_dir_fd=dirfd ,follow_symlinks=False)
        os.unlink(tmp ,dir_fd=dirfd)
        self._log("created" ,where)
      else:
        kept = None
        if record["mode"] == "replace-keep" and not is__absent(dirfd ,filen__target):
          kept = _backup_name(dirfd ,filen__target)
          os.link(filen__target ,kept ,src_dir_fd=dirfd ,dst_dir_fd=dirfd ,follow_symlinks=False)
        os.rename(tmp ,filen__target ,src_dir_fd=dirfd ,dst_dir_fd=dirfd)
        self._log("replaced" ,where + (f" (kept as {kept})" if kept else ""))
      record["tmp"] = None
      os.fsync(dirfd)

  def release(self):
    for record in self._opened:
      if record["fd"] is not None:
        os.close(record["fd"])
      if record["tmp"] is not None:
        try:
          os.unlink(record["tmp"] ,dir_fd=record["dirfd"])
        except OSError:
          pass
      os.close(record["dirfd"])
