#!/usr/bin/env -S python3 -B
# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Man-In-Grey

The orchestrator. It runs a composer, which declares variables and places
instructions into a journal, and invokes a gate with the journal on its
standard input. The gate starts the guard, which checks the journal against
the language definition and the constraints, and, when the guard passes the
journal, the interpreter, which plays it. When the journal declares a
result, the gate hands it back on descriptor 3, and the orchestrator prints
it.

A composer is a Python file defining compose(prov ,journal_iface). prov
describes where the composer is; journal_iface has a function for each
instruction of the gate's instruction language, and declare and result. The
orchestrator learns the language from the gate's flags, and loads the
definition named for it: Emplace_Bio from Emplace_Bio·Language.py.

Usage: Man-In-Grey <command> ...
  help | -h                  print this message (also printed when given no arguments)
  orchestrate <composer> gate <file> [option ...]
                             <composer> is a composer file; <file> is the gate to
                             invoke, which also sets the instruction language the
                             composer writes in
  install <gate> owner <account> [group <group>] into <directory> [constraints <file>]
                             install a gate setuid and setgid, by running install-gate
                             as root; when not run by root, su asks for root's password;
                             see install-gate for the rest

Options of orchestrate:
  print                      print the journal after composing
  compose-only               stop after composing; nothing reaches the gate
  check-only                 have the gate run the guard and not the interpreter

The composer, and every directory from / down to it, is to be owned by the
gate invoking account or by root, and writable by no other account. A
composer that is a symbolic link is refused.

A result is printed as one line, result: <type name> <value>. A descriptor
the result holds is shown as <descriptor>, and closed, as the orchestrator
has no use for it; an application that is its own orchestrator calls admit
and keeps it.

Exit status: 0 when the run did what it was asked; 1 when the guard refused
the journal or an instruction failed to execute; 2 when the run could not start,
the composer failed, or the gate, guard or interpreter could not run.
"""

import sys ,os
sys.dont_write_bytecode = True

import datetime ,importlib ,pwd ,re ,runpy ,shlex ,socket ,stat ,subprocess ,traceback
from pathlib import Path

import Language
import Journal
import Journal·Interface

# The promoted layout: this file in Man_In_Grey/, beside Man_In_Grey__Gate/.
# The same layout is staged in developer/scratchpad/made/ and promoted to consumer/.
DIRPA__HERE = Path(__file__).resolve().parent

FLAG = ("print" ,"compose-only" ,"check-only")
VALUE = ("gate" ,)
COMMAND = ("orchestrate" ,)


def gate_invoking_account__name():
  return pwd.getpwuid(os.getuid()).pw_name


# --------------------------------------------------------------------------------
# provenance

class Provenance:
  """
  Where a composer is. Given to compose().
  """
  __slots__ = (
    "fpa__composer"
    ,"dirpa__composer"
    ,"filen__implied"
    ,"process_user"
    ,"dirpa__cwd"
  )

  def __init__(self ,fpa__composer):
    self.fpa__composer = fpa__composer
    self.dirpa__composer = fpa__composer.parent
    name = fpa__composer.name
    if name.endswith(".py"):
      name = name[:-3]
    self.filen__implied = name
    self.process_user = gate_invoking_account__name()
    self.dirpa__cwd = Path.cwd().resolve()


# --------------------------------------------------------------------------------
# finding the composers, and the ownership check

def trusted_owner__problem(fsnodp__checked):
  "None when path is owned by the gate invoking account or root and writable by no other account"
  try:
    st = os.lstat(fsnodp__checked)
  except OSError as error:
    return f"{fsnodp__checked}: {error.strerror}"
  if st.st_uid not in (0 ,os.getuid()):
    return f"{fsnodp__checked} is owned by uid {st.st_uid}, neither root nor the gate invoking account"
  if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
    return f"{fsnodp__checked} is writable by group or other accounts"
  return None

def chain_problem(fsnodpa__checked):
  "the ownership check over path and every directory above it"
  for each in [fsnodpa__checked] + list(fsnodpa__checked.parents):
    problem = trusted_owner__problem(each)
    if problem:
      return problem
  return None

def composer_provenance(fpa__composer):
  """
  Given a composer file, absolute. Returns its Provenance. Raises
  RuntimeError on a symbolic link, a file that is not regular, or a failed
  ownership check.
  """
  problem = chain_problem(fpa__composer)
  if problem:
    raise RuntimeError(f"refusing to run the composer: {problem}")
  if fpa__composer.is_symlink():
    raise RuntimeError(f"{fpa__composer} is a symbolic link")
  if fpa__composer.is_dir():
    raise RuntimeError(f"{fpa__composer} is a directory; this version of Man-In-Grey runs one composer, given as a file")
  if not stat.S_ISREG(fpa__composer.lstat().st_mode):
    raise RuntimeError(f"{fpa__composer} is not a composer file")
  return Provenance(fpa__composer)


# --------------------------------------------------------------------------------
# the gate's language

def gate_flag(fpa__gate):
  """The gate's flags as a dict. Raises RuntimeError."""
  if not os.access(fpa__gate ,os.X_OK):
    raise RuntimeError(f"the gate {fpa__gate} is missing; in the developer role, build and promote it")
  result = subprocess.run([str(fpa__gate) ,"flags"] ,capture_output=True ,text=True)
  if result.returncode != 0:
    raise RuntimeError(f"the gate {fpa__gate} did not report its flags")
  return dict(line.split("=" ,1) for line in result.stdout.splitlines() if "=" in line)

def language_definition(name):
  """
  The definition of an instruction language: Emplace_Bio's is in
  Emplace_Bio·Language.py, beside this file. Raises RuntimeError.
  """
  if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*" ,name or ""):
    raise RuntimeError(f"the gate names the language {name!r}, which names no definition")
  # a language is named by its namespace, so the name is the module's prefix
  module = name + "·Language"
  if not (DIRPA__HERE / f"{module}.py").is_file():
    raise RuntimeError(f"the gate's language is {name}, and {module}.py is not beside {Path(__file__).name}")
  definition_module = importlib.import_module(module)
  if getattr(definition_module ,"NAME" ,None) != name:
    raise RuntimeError(f"{module}.py is not the definition of the language {name}")
  try:
    return Language.Definition(name ,definition_module.DEFINITION)
  except Language.DefinitionError as error:
    raise RuntimeError(str(error))


# --------------------------------------------------------------------------------
# composing, and invoking the gate

def compose(prov ,language_definition):
  """Run the composer into a journal. Raises RuntimeError naming the composer when it fails."""
  journal = Journal·Interface.JournalComposed(language_definition)
  journal_iface = Journal·Interface.JournalInterface(journal)
  name = prov.fpa__composer.name
  try:
    env = runpy.run_path(str(prov.fpa__composer))
    function = env.get("compose")
    if not callable(function):
      raise RuntimeError("defines no compose(prov ,journal_iface)")
    function(prov ,journal_iface)
    journal.as_data()   # a result declared and never written is refused here
  except Journal.JournalError as error:
    raise RuntimeError(f"{name}: {error}")
  except RuntimeError as error:
    raise RuntimeError(f"{name}: {error}")
  except Exception:
    raise RuntimeError(f"{name}: the composer raised an error\n{traceback.format_exc()}")
  journal.meta = {
    "composed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    ,"process_user": gate_invoking_account__name()
    ,"host": os.uname().nodename
    ,"composer": str(prov.fpa__composer)
  }
  return journal

RESULT_FD = 3
DESCRIPTOR_MAX = 16   # the most the gate hands back beside a result, as in Gate.lib.c

def admit(fpa__gate ,journal_bytes ,check_only=False):
  """
  Invoke the gate with the journal on its standard input, and descriptor 3
  open to receive the result. The gate's standard output and standard error
  are this process's. Returns (status ,result ,list__fd), where result is
  the bytes the gate wrote on descriptor 3, empty when there was none, and
  list__fd the open descriptors that came beside them, in the order they
  came. Journal.decode_result(result ,list__fd) puts each in its place in
  the result's value; closing them is the caller's.

  Descriptor 3 is one end of a Unix socket pair, which exists only as the
  two descriptors, with no file on disk. Over a pipe only bytes travel; over
  a Unix socket the kernel also passes open descriptors, as SCM_RIGHTS,
  opening each again in the receiving process under a number of its own.

  An application that is its own orchestrator calls this function with the
  journal it made.
  """
  command = [str(fpa__gate) ,"admit"] + (["check-only"] if check_only else [])
  socket__gate ,socket__here = socket.socketpair(socket.AF_UNIX ,socket.SOCK_STREAM)
  fd__gate = socket__gate.fileno()
  def give_result_descriptor():
    # Runs in the child, before the gate starts. Python makes descriptors
    # close-on-exec; dup2 gives descriptor 3 without that mark, except onto
    # itself, which changes nothing, so that case is marked inheritable.
    if fd__gate == RESULT_FD:
      os.set_inheritable(RESULT_FD ,True)
    else:
      os.dup2(fd__gate ,RESULT_FD)
  try:
    gate = subprocess.Popen(command ,stdin=subprocess.PIPE ,close_fds=False ,preexec_fn=give_result_descriptor)
  except BaseException:
    socket__gate.close(); socket__here.close()
    raise
  socket__gate.close()
  try:
    gate.stdin.write(journal_bytes)
  except BrokenPipeError:
    pass
  finally:
    try:
      gate.stdin.close()
    except BrokenPipeError:
      pass
  list__part ,list__fd = [] ,[]
  with socket__here:
    while True:
      part ,list__received ,_ ,_ = socket.recv_fds(socket__here ,1 << 16 ,DESCRIPTOR_MAX ,socket.MSG_CMSG_CLOEXEC)
      list__fd.extend(list__received)
      if not part: break
      list__part.append(part)
  return gate.wait() ,b"".join(list__part) ,list__fd

class DescriptorShown:
  "stands in a printed result where a descriptor came"
  def __repr__(self):
    return "<descriptor>"

def print_result(result_bytes ,list__fd=() ,file=None):
  """
  One line, result: <type name> <value>, with bytes shown by their count
  and each descriptor as <descriptor>. The descriptors are closed.
  """
  try:
    type_name ,value = Journal.decode_result(result_bytes ,[DescriptorShown() for _ in list__fd])
  except Journal.JournalError as error:
    print(f"error: {error}" ,file=sys.stderr)
    return False
  finally:
    for fd in list__fd:
      os.close(fd)
  shown = f"<{len(value)} bytes>" if type(value) is bytes else repr(value)
  print(f"result: {type_name} {shown}" ,file=file or sys.stdout)
  return True

def orchestrate(filep__composer ,gate ,flag):
  filep__composer = Path(filep__composer).absolute()
  if not gate:
    print("error: orchestrate is given the gate to invoke, as gate <file>" ,file=sys.stderr)
    return 2
  fpa__gate = Path(gate).absolute()
  try:
    journal = compose(composer_provenance(filep__composer) ,language_definition(gate_flag(fpa__gate).get("language")))
  except (OSError ,RuntimeError) as error:
    print(f"error: {error}" ,file=sys.stderr)
    return 2
  if "print" in flag:
    journal.print()
  if "compose-only" in flag:
    return 0
  sys.stdout.flush()
  status ,result ,list__fd = admit(fpa__gate ,journal.encode() ,"check-only" in flag)
  if result and not print_result(result ,list__fd):
    return 2
  for fd in ([] if result else list__fd):
    os.close(fd)
  return status


# --------------------------------------------------------------------------------
# command line

def print_help():
  print(__doc__.strip())
  return 0

# --------------------------------------------------------------------------------
# installing a gate

def install(list__argument):
  """
  Run install-gate install with the arguments given, as root. Run by root, it
  runs install-gate itself; run by anyone else, it runs it through su, which
  asks for root's password. A constraints file is made absolute first, as
  root's shell starts elsewhere. Returns install-gate's exit status.
  """
  list__argument = list(list__argument)
  for i ,word in enumerate(list__argument[:-1]):
    if word == "constraints":
      list__argument[i + 1] = str(Path(list__argument[i + 1]).absolute())
  command = [str(DIRPA__HERE / "install-gate") ,"install" ,*list__argument]
  if os.geteuid() != 0:
    print("install-gate is run by root; su asks for root's password" ,file=sys.stderr)
    command = ["su" ,"root" ,"-c" ,shlex.join(command)]
  return subprocess.run(command).returncode


def CLI(argv=None):
  argv = sys.argv[1:] if argv is None else argv
  if not argv or argv[0] in ("help" ,"-h" ,"--help"): return print_help()
  command ,rest = argv[0] ,argv[1:]
  if command == "install":
    return install(rest)
  if command not in COMMAND:
    print(f"Error: unknown command '{command}'." ,file=sys.stderr)
    print_help()
    return 2
  if not rest:
    print(f"Error: {command} is given a composer file." ,file=sys.stderr)
    return 2
  filep__composer ,rest = rest[0] ,rest[1:]
  value ,flag = {} ,set()
  i = 0
  while i < len(rest):
    word = rest[i]
    if word in VALUE and i + 1 < len(rest):
      value[word] = rest[i + 1]; i += 2
    elif word in FLAG:
      flag.add(word); i += 1
    else:
      print(f"Error: unknown or incomplete option '{word}'." ,file=sys.stderr)
      return 2
  return orchestrate(filep__composer ,value.get("gate") ,flag)


if __name__ == "__main__":
  sys.exit(CLI())
