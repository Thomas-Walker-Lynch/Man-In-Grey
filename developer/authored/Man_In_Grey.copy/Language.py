# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Language - what a Man-In-Grey instruction language is, and how its definition is checked.

This module defines no language. An instruction language is defined by its
application developer as data: a map of four sections, written as a literal
value in a module of its own, such as Emplace_Bio·Language.py. Account A
cannot change it. The guard, the interpreter and the journal interface all
read the same definition, and a journal carries the hash of the definition
it was composed against.

  list__type     a list of type declarations, each [<name> ,<type expression>].
                A type expression is a primitive, the name of a type declared
                earlier in the list, or a compound:
                  ["dictionary" ,[<key> ,<type expression>] ...]
                  ["list" ,<type expression>]
  list__format   a list of instruction formats, each
                [<format name> ,[<direction> ,<type name>] ...], where the
                direction is in, out or in-out, and the type name is a
                primitive or a declared type. Arguments are given by position.
  list__result   the list of type names a journal's result can have.
  map__instruction
                a map from each operation specifier to its format name. The
                operation specifier is also the name of the function that
                carries out the instruction.

The primitives are text, integer, bytes, boolean, handle and descriptor.
Two of them are values only an instruction produces, so no literal can be
one:

  handle       a value an instruction produces for later instructions, such
               as an open file; it means nothing outside the interpreter, so
               no result can hold one
  descriptor   an open file descriptor an instruction produces, which a
               result can hold: the interpreter sends it to the gate beside
               the result's bytes, as SCM_RIGHTS over a Unix socket, and the
               gate hands it on to whoever invoked it. The descriptor's number
               means nothing in another process, so in the encoded result each
               descriptor is the CBOR tag TAG__DESCRIPTOR holding its position
               among the descriptors sent; descriptor_mark makes that form,
               and Journal.decode_result puts the received descriptors back

Types are compared by name. A variable of the type short_name is not a
variable of the type text, even when short_name is declared as text, so a
reference passes only where the format names its type exactly. A literal is
compared with the type's structure.

This module is a library. is__well_formed_language(data ,report) answers
whether a definition is well formed, reporting each problem;
Definition(name ,data) is a definition that has passed, as the guard, the
interpreter and the journal interface each use it.
"""

import hashlib ,keyword

import cbor2

LIST__PRIMITIVE = ("text" ,"integer" ,"bytes" ,"boolean" ,"handle" ,"descriptor")
LIST__PRIMITIVE__PRODUCED = ("handle" ,"descriptor")   # never a literal

# The CBOR tag that stands for a descriptor in an encoded result: the bytes of
# "MIG" read as a number. A tag is part of CBOR's structure, never of a value's
# content, so no text or bytes in a result can be taken for one.
TAG__DESCRIPTOR = 0x4D4947
LIST__COMPOUND = ("dictionary" ,"list")
LIST__DIRECTION = ("in" ,"out" ,"in-out")
LIST__SECTION = ("list__type" ,"list__format" ,"list__result" ,"map__instruction")

# operation specifiers the journal interface and the interpreter keep for themselves
LIST__OPERATION_RESERVED = ("declare" ,"result" ,"finish" ,"release")


class DefinitionError(Exception):
  """A language definition is not well formed."""


def is__control(character):
  code = ord(character)
  return code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F

def is__name(value):
  "True for a name: text that is not empty and holds no space and no control character"
  return type(value) is str and value != "" and not any(c.isspace() or is__control(c) for c in value)

def hash_text(data):
  "the SHA-256 of a definition's canonical CBOR encoding, in hexadecimal"
  return hashlib.sha256(cbor2.dumps(data ,canonical=True)).hexdigest()


# --------------------------------------------------------------------------------
# the well-formed check of a definition

def _type_expression__problem(expression ,map__type ,where):
  "None when expression is a well-formed type expression over the primitives and the types in map__type"
  if type(expression) is str:
    if expression in LIST__PRIMITIVE or expression in map__type:
      return None
    return f"{where}: {expression!r} is neither a primitive nor a type declared before it"
  if type(expression) is not list or not expression:
    return f"{where}: a type expression is a type name or a list beginning with dictionary or list"
  head = expression[0]
  if head == "list":
    if len(expression) != 2:
      return f"{where}: a list type is [\"list\" ,<element type>]"
    return _type_expression__problem(expression[1] ,map__type ,f"{where} list element")
  if head == "dictionary":
    set__key = set()
    for entry in expression[1:]:
      if type(entry) is not list or len(entry) != 2 or not is__name(entry[0]):
        return f"{where}: a dictionary entry is [<key> ,<type expression>]"
      if entry[0] in set__key:
        return f"{where}: the key {entry[0]!r} is given twice"
      set__key.add(entry[0])
      problem = _type_expression__problem(entry[1] ,map__type ,f"{where} key {entry[0]}")
      if problem: return problem
    return None
  return f"{where}: {head!r} is not a compound type; the compounds are {', '.join(LIST__COMPOUND)}"

def _is__holder(expression ,map__type ,set__primitive):
  "True when the type expression is, or holds, one of the primitives in set__primitive"
  if type(expression) is str:
    if expression in set__primitive: return True
    if expression in map__type: return _is__holder(map__type[expression] ,map__type ,set__primitive)
    return False
  if expression[0] == "list":
    return _is__holder(expression[1] ,map__type ,set__primitive)
  return any(_is__holder(entry[1] ,map__type ,set__primitive) for entry in expression[1:])

def _is__handle_holder(expression ,map__type):
  "True when the type expression is, or holds, a handle"
  return _is__holder(expression ,map__type ,("handle",))

def list__problem_language(data):
  "every problem with a language definition, as a list of messages; empty when it is well formed"
  if type(data) is not dict:
    return ["the definition is not a map"]
  if set(data) != set(LIST__SECTION):
    return [f"the definition has the sections {sorted(data)}; it is to have exactly {list(LIST__SECTION)}"]
  list__problem = []

  map__type = {}
  if type(data["list__type"]) is not list:
    list__problem.append("list__type: is not a list")
  else:
    for index ,entry in enumerate(data["list__type"]):
      where = f"list__type @{index}"
      if type(entry) is not list or len(entry) != 2:
        list__problem.append(f"{where}: a type declaration is [<name> ,<type expression>]"); continue
      name ,expression = entry
      if not is__name(name):
        list__problem.append(f"{where}: {name!r} is not a name"); continue
      if name in LIST__PRIMITIVE or name in LIST__COMPOUND or name in map__type:
        list__problem.append(f"{where}: the type name {name!r} is a primitive, a compound or declared before"); continue
      problem = _type_expression__problem(expression ,map__type ,f"{where} {name}")
      if problem: list__problem.append(problem); continue
      map__type[name] = expression

  set__format_name = set()
  if type(data["list__format"]) is not list:
    list__problem.append("list__format: is not a list")
  else:
    for index ,entry in enumerate(data["list__format"]):
      where = f"list__format @{index}"
      if type(entry) is not list or not entry or not is__name(entry[0]):
        list__problem.append(f"{where}: an instruction format is [<format name> ,[<direction> ,<type name>] ...]"); continue
      name = entry[0]
      if name in set__format_name:
        list__problem.append(f"{where}: the format {name!r} is declared twice"); continue
      set__format_name.add(name)
      for position ,argument in enumerate(entry[1:]):
        if type(argument) is not list or len(argument) != 2:
          list__problem.append(f"{where} {name} argument {position}: an argument is [<direction> ,<type name>]"); continue
        direction ,type_name = argument
        if direction not in LIST__DIRECTION:
          list__problem.append(f"{where} {name} argument {position}: {direction!r} is not one of {', '.join(LIST__DIRECTION)}")
        if type(type_name) is not str or not (type_name in LIST__PRIMITIVE or type_name in map__type):
          list__problem.append(f"{where} {name} argument {position}: {type_name!r} is neither a primitive nor a declared type")

  if type(data["list__result"]) is not list:
    list__problem.append("list__result: is not a list")
  else:
    for type_name in data["list__result"]:
      if type(type_name) is not str or not (type_name in LIST__PRIMITIVE or type_name in map__type):
        list__problem.append(f"list__result: {type_name!r} is neither a primitive nor a declared type"); continue
      if _is__handle_holder(type_name ,map__type):
        list__problem.append(f"list__result: {type_name!r} holds a handle, which has no meaning outside the interpreter")
    if len(set(map(repr ,data["list__result"]))) != len(data["list__result"]):
      list__problem.append("list__result: a type is given twice")

  if type(data["map__instruction"]) is not dict or not data["map__instruction"]:
    list__problem.append("map__instruction: is not a map of at least one operation specifier to its format name")
  else:
    for operation ,format_name in data["map__instruction"].items():
      if type(operation) is not str or not operation.isidentifier() or keyword.iskeyword(operation) or operation.startswith("_"):
        list__problem.append(f"map__instruction: {operation!r} is not an operation specifier; it is a Python function name not beginning with _"); continue
      if operation in LIST__OPERATION_RESERVED:
        list__problem.append(f"map__instruction: {operation!r} is kept by Man-In-Grey; the kept names are {', '.join(LIST__OPERATION_RESERVED)}")
      if format_name not in set__format_name:
        list__problem.append(f"map__instruction: {operation} has the format {format_name!r}, which is not declared")
  return list__problem

def is__well_formed_language(data ,report):
  """
  True when the language definition data is well formed. Each problem found
  is given to report(tag ,message), as definition-broken.
  """
  list__problem = list__problem_language(data)
  for problem in list__problem:
    report("definition-broken" ,problem)
  return not list__problem


# --------------------------------------------------------------------------------
# a checked definition

class Definition:
  """
  A language definition that has passed its well-formed check. Given the
  language's name and the definition data. Raises DefinitionError.
  """

  def __init__(self ,name ,data):
    list__problem = list__problem_language(data)
    if list__problem:
      raise DefinitionError(f"the definition of {name} is not well formed: " + "; ".join(list__problem))
    self.name = name
    self.data = data
    self.hash = hash_text(data)
    self._map__type = {entry[0]: entry[1] for entry in data["list__type"]}
    self._map__format = {entry[0]: [tuple(argument) for argument in entry[1:]] for entry in data["list__format"]}
    self.list__result_type = list(data["list__result"])
    self.list__operation = list(data["map__instruction"])

  def is__type_name(self ,name):
    return type(name) is str and (name in LIST__PRIMITIVE or name in self._map__type)

  def format_of(self ,operation):
    "the arguments of the operation's format, as (direction ,type name) in order; None for an unknown operation"
    format_name = self.data["map__instruction"].get(operation) if type(operation) is str else None
    return None if format_name is None else self._map__format[format_name]

  def is__handle_holder(self ,type_name):
    return _is__handle_holder(type_name ,self._map__type)

  def is__produced_holder(self ,type_name):
    "True when the type is, or holds, a value only an instruction produces, a handle or a descriptor"
    return _is__holder(type_name ,self._map__type ,LIST__PRIMITIVE__PRODUCED)

  def descriptor_mark(self ,value ,expression):
    """
    (marked ,list__fd) for a value of the type expression, already checked
    by value_problem: marked is the value with each descriptor replaced by
    the CBOR tag TAG__DESCRIPTOR holding its position in list__fd, and
    list__fd is the descriptors, in the order met, depth first.
    """
    list__fd = []
    def mark(value ,expression):
      if type(expression) is str:
        if expression in self._map__type:
          return mark(value ,self._map__type[expression])
        if expression == "descriptor":
          list__fd.append(value)
          return cbor2.CBORTag(TAG__DESCRIPTOR ,len(list__fd) - 1)
        return value
      if expression[0] == "list":
        return [mark(element ,expression[1]) for element in value]
      return {entry[0]: mark(value[entry[0]] ,entry[1]) for entry in expression[1:]}
    return mark(value ,expression) ,list__fd

  def value_problem(self ,value ,expression ,where="the value"):
    """
    None when value has the structure of the type expression; otherwise what
    is wrong. Checks type() exactly, so that a boolean is never taken for an
    integer, as isinstance(True ,int) would.
    """
    if type(expression) is str:
      if expression in self._map__type:
        return self.value_problem(value ,self._map__type[expression] ,where)
      want = {"text": str ,"integer": int ,"bytes": bytes ,"boolean": bool ,"handle": int ,"descriptor": int}[expression]
      if type(value) is not want:
        return f"{where} is {type(value).__name__}, not {expression}"
      if expression == "descriptor" and value < 0:
        return f"{where} is {value}, which is not an open descriptor"
      return None
    if expression[0] == "list":
      if type(value) is not list:
        return f"{where} is {type(value).__name__}, not a list"
      for i ,element in enumerate(value):
        problem = self.value_problem(element ,expression[1] ,f"{where}[{i}]")
        if problem: return problem
      return None
    map__key_type = {entry[0]: entry[1] for entry in expression[1:]}
    if type(value) is not dict:
      return f"{where} is {type(value).__name__}, not a dictionary"
    if set(value) != set(map__key_type):
      return f"{where} has the keys {sorted(map(str ,value))}, not {sorted(map__key_type)}"
    for key ,element_type in map__key_type.items():
      problem = self.value_problem(value[key] ,element_type ,f"{where}[{key!r}]")
      if problem: return problem
    return None
