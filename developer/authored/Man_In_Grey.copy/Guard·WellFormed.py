# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Guard·WellFormed - the well-formed guard: a journal checked against its language definition.

A journal is straight-line: no branch, no loop. So one pass from first
instruction to last settles, for every argument, whether it is well formed:
every variable is declared, its type is the type the format names, it is
written before it is read, and the result is written by the end. Scan makes
that pass. The guard and the interpreter make it on the journal they
receive, through is__well_formed_journal; the journal interface makes it as
each instruction is placed, so a composer's mistake is an error when the
composer makes it.

The pass also resolves each instruction for the language's own checks, as
InstructionView: the values of its literals, and for each variable the
instruction that last wrote it.

This module is a library.
"""

from Journal import clean ,LIST__KIND
from Language import is__name


class Argument:
  """
  One argument of an instruction, as the language's checks see it. A literal
  has its value; a variable has its name, its direction, and source, the
  index of the instruction that last wrote it before this one, or None when
  this instruction is the first to write it.
  """
  __slots__ = ("kind" ,"value" ,"name" ,"direction" ,"source")

  def __init__(self ,kind ,value=None ,name=None ,direction="in" ,source=None):
    self.kind = kind
    self.value = value
    self.name = name
    self.direction = direction
    self.source = source

  def is__literal(self):
    return self.kind == "literal"


class InstructionView:
  """An instruction as the language's checks see it: its index, operation specifier and arguments."""
  __slots__ = ("index" ,"operation" ,"list__argument")

  def __init__(self ,index ,operation ,list__argument):
    self.index = index
    self.operation = operation
    self.list__argument = list__argument


class Scan:
  """
  The state of one pass over a journal: the variables declared, and for each
  the instruction that last wrote it. Given the language definition. declare,
  instruction and result each return a list of problems, empty when they
  accept, and record what they accept.
  """

  def __init__(self ,language_definition):
    self.language_definition = language_definition
    self.map__declared = {}           # variable name -> type name
    self.map__writer = {}             # variable name -> index of the instruction that last wrote it
    self.list__instruction_view = []

  def declare(self ,name ,type_name):
    if not is__name(name):
      return [f"variable {clean(repr(name))} is not a name"]
    if name in self.map__declared:
      return [f"variable {clean(name)} is declared twice"]
    if not self.language_definition.is__type_name(type_name):
      return [f"variable {clean(name)}: {clean(repr(type_name))} is not a type of the language {self.language_definition.name}"]
    self.map__declared[name] = type_name
    return []

  def instruction(self ,index ,operation ,list__pair):
    definition = self.language_definition
    where = f"@{index} {clean(operation)}"
    format_ = definition.format_of(operation)
    if format_ is None:
      return [f"@{index}: {clean(repr(operation))} is not an operation of the language {definition.name}"]
    if type(list__pair) is not list or len(list__pair) != len(format_):
      count = len(list__pair) if type(list__pair) is list else "no list of"
      return [f"{where}: {count} arguments; the format takes {len(format_)}"]
    list__problem = []
    list__argument = []
    list__written_here = []
    for position ,(pair ,(direction ,type_name)) in enumerate(zip(list__pair ,format_)):
      at = f"{where} argument {position}"
      if type(pair) is not list or len(pair) != 2 or pair[0] not in LIST__KIND:
        list__problem.append(f"{at}: an argument is [\"literal\" ,<value>] or [\"variable\" ,<name>]"); continue
      kind ,payload = pair
      if kind == "literal":
        if direction != "in":
          list__problem.append(f"{at}: a literal is given where the format writes ({direction})"); continue
        if definition.is__produced_holder(type_name):
          list__problem.append(f"{at}: the type {type_name} holds a handle or a descriptor, which only an instruction produces, never a literal"); continue
        problem = definition.value_problem(payload ,type_name ,"the literal")
        if problem:
          list__problem.append(f"{at}: {clean(problem)}, as the type {type_name} requires"); continue
        list__argument.append(Argument("literal" ,value=payload))
        continue
      name = payload
      if type(name) is not str or name not in self.map__declared:
        list__problem.append(f"{at}: the variable {clean(repr(name))} is not declared"); continue
      if self.map__declared[name] != type_name:
        list__problem.append(f"{at}: the variable {clean(name)} is of the type {self.map__declared[name]}; the format takes {type_name}"); continue
      if direction in ("in" ,"in-out") and name not in self.map__writer:
        list__problem.append(f"{at}: the variable {clean(name)} is read before any instruction writes it"); continue
      if direction in ("out" ,"in-out"):
        if name in list__written_here or any(a.kind == "variable" and a.name == name for a in list__argument):
          list__problem.append(f"{at}: the variable {clean(name)} is written here and given again in the same instruction"); continue
        list__written_here.append(name)
      elif name in list__written_here:
        list__problem.append(f"{at}: the variable {clean(name)} is written here and given again in the same instruction"); continue
      list__argument.append(Argument("variable" ,name=name ,direction=direction ,source=self.map__writer.get(name)))
    if list__problem:
      return list__problem
    for name in list__written_here:
      self.map__writer[name] = index
    self.list__instruction_view.append(InstructionView(index ,operation ,list__argument))
    return []

  def result(self ,name):
    if name is None:
      return []
    if type(name) is not str or name not in self.map__declared:
      return [f"the result {clean(repr(name))} is not a declared variable"]
    type_name = self.map__declared[name]
    if type_name not in self.language_definition.list__result_type:
      return [f"the result {clean(name)} is of the type {type_name}, which is not among the result types {self.language_definition.list__result_type}"]
    if name not in self.map__writer:
      return [f"the result {clean(name)} is never written"]
    return []


def scan_journal(data ,language_definition):
  """
  Make the pass over a decoded journal. Returns (list__problem ,scan); the
  scan's list__instruction_view is complete only when there is no problem.
  """
  scan = Scan(language_definition)
  if data["instruction_language"] != language_definition.name:
    return [f"the journal is in {clean(repr(data['instruction_language']))}; this is {language_definition.name}"] ,scan
  if data["definition_hash"] != language_definition.hash:
    return [f"the journal was composed against another definition of {language_definition.name}"
            f" (hash {clean(str(data['definition_hash'])[:16])}..., not {language_definition.hash[:16]}...);"
            " the composer's copy of the definition and the guard's differ"] ,scan
  list__problem = []
  for index ,entry in enumerate(data["list__variable"]):
    if type(entry) is not list or len(entry) != 2:
      list__problem.append(f"variable @{index}: a declaration is [<name> ,<type name>]"); continue
    list__problem += scan.declare(*entry)
  if list__problem:
    return list__problem ,scan
  for index ,instruction in enumerate(data["list__instruction"]):
    list__problem += scan.instruction(index ,instruction["operation"] ,instruction["list__argument"])
  if list__problem:
    return list__problem ,scan
  return scan.result(data["result"]) ,scan

def is__well_formed_journal(data ,language_definition ,report):
  """
  True when the decoded journal is well formed against the language
  definition. Each problem found is given to report(tag ,message), as
  wellformed-broken.
  """
  list__problem ,_ = scan_journal(data ,language_definition)
  for problem in list__problem:
    report("wellformed-broken" ,problem)
  return not list__problem

def make__list__instruction_view(data ,language_definition):
  """
  The instructions of a well-formed journal as InstructionView, for the
  language's checks and the interpreter. Raises ValueError on a journal that
  is not well formed; call is__well_formed_journal first.
  """
  list__problem ,scan = scan_journal(data ,language_definition)
  if list__problem:
    raise ValueError(f"the journal is not well formed: {list__problem[0]}")
  return scan.list__instruction_view
