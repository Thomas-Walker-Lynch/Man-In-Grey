# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Journal - the journal of Man-In-Grey, independent of any command language.

A composer places commands into a journal. A command is data: the name of
the command, its arguments, and the composer that placed it. A command whose
execution produces a value, such as an open file, is given a symbol when it
is placed. A later command names that symbol where it needs the value. The
value does not exist until the journal interpreter executes the command, so
the composer holds the symbol and nothing more.

The journal travels to the journal interpreter encoded in CBOR. CBOR carries
strings and byte strings with their lengths, so content is never scanned for
marks, and decoding it makes maps, lists, strings and bytes, never code.

A command language is defined elsewhere, as a module with a composer half,
its journal interface, and an interpreter half, its guard and executor.
"""

import cbor2

JOURNAL_VERSION = 2


class JournalError(Exception):
  """A journal interface call was given a wrong argument, or a journal is malformed."""


class Symbol:
  """
  The value a command will produce when it is executed. A symbol is the
  index of the command that produces it, counted from 0. It is encoded in the
  journal as {"symbol": index}.
  """
  __slots__ = ("index" ,)

  def __init__(self ,index):
    self.index = index

  def as_data(self):
    return {"symbol": self.index}

  def __repr__(self):
    return f"Symbol({self.index})"

  @staticmethod
  def is_data(value):
    return isinstance(value ,dict) and set(value) == {"symbol"} and isinstance(value["symbol"] ,int)


class Command:
  __slots__ = ("command" ,"argument" ,"composer")

  def __init__(self ,command ,argument ,composer):
    self.command = command
    self.argument = argument
    self.composer = composer

  def as_data(self):
    return {
      "command": self.command
      ,"argument": {k: (v.as_data() if isinstance(v ,Symbol) else v) for k ,v in self.argument.items()}
      ,"composer": self.composer
    }


class Journal:
  """
  The commands of one run, in order, for one command language. principal is
  the account the journal was composed on behalf of, when that is not the
  account that hands it to the gate.
  """

  def __init__(self ,command_language ,principal=None):
    self.command_language = command_language
    self.principal = principal
    self.meta = {}
    self.command_list = []
    self.composer = None

  def place(self ,command ,argument):
    """Place a command; returns its symbol."""
    self.command_list.append(Command(command ,dict(argument) ,self.composer))
    return Symbol(len(self.command_list) - 1)

  def as_data(self):
    data = {
      "version": JOURNAL_VERSION
      ,"command_language": self.command_language
      ,"meta": dict(self.meta)
      ,"command_list": [c.as_data() for c in self.command_list]
    }
    if self.principal is not None:
      data["principal"] = self.principal
    return data

  def encode(self):
    return cbor2.dumps(self.as_data() ,canonical=True)

  def print(self ,file=None):
    import sys
    file = file or sys.stdout
    if not self.command_list:
      print("(the journal is empty)" ,file=file)
    for index ,command in enumerate(self.command_list):
      print(command_line(index ,command.as_data()) ,file=file)


def decode(journal_bytes):
  """
  Decode a journal from CBOR into its data, checking only the shape common to
  every command language. Raises JournalError.
  """
  try:
    data = cbor2.loads(journal_bytes)
  except Exception as error:
    raise JournalError(f"the journal is not valid CBOR: {error}")
  if not isinstance(data ,dict):
    raise JournalError("the journal is not a map")
  if data.get("version") != JOURNAL_VERSION:
    raise JournalError(f"journal version {data.get('version')!r}; this interpreter reads version {JOURNAL_VERSION}")
  if not isinstance(data.get("command_language") ,str):
    raise JournalError("the journal names no command language")
  if "principal" in data and not isinstance(data["principal"] ,str):
    raise JournalError("the journal's principal is not an account name")
  command_list = data.get("command_list")
  if not isinstance(command_list ,list):
    raise JournalError("the journal has no command list")
  for index ,command in enumerate(command_list):
    if not (isinstance(command ,dict) and isinstance(command.get("command") ,str) and isinstance(command.get("argument") ,dict)):
      raise JournalError(f"command {index} is not a command")
    for name ,value in command["argument"].items():
      if isinstance(value ,dict) and not Symbol.is_data(value):
        raise JournalError(f"command {index}: argument {name} is neither a value nor a symbol")
      if Symbol.is_data(value) and not (0 <= value["symbol"] < index):
        raise JournalError(f"command {index}: argument {name} names symbol {value['symbol']}, which no earlier command produces")
  return data


def command_line(index ,command):
  """One line describing a command, for printing a journal."""
  part = []
  for name ,value in command["argument"].items():
    if Symbol.is_data(value):
      part.append(f"{name}=@{value['symbol']}")
    elif isinstance(value ,(bytes ,bytearray)):
      part.append(f"{name}=<{len(value)} bytes>")
    elif name == "permission" and isinstance(value ,int):
      part.append(f"{name}={value:04o}")
    else:
      part.append(f"{name}={value!r}")
  composer = command.get("composer")
  return f"@{index:<3} {command['command']:<8} {' '.join(part)}" + (f"   ({composer})" if composer else "")
