# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Interpreter - the general interpreter of Man-In-Grey.

The interpreter plays a journal the guard has passed. It carries out the
instructions and does not judge them, with one exception: it makes the
well-formed check again, since it decodes the journal anyway, so that a
malformed journal never reaches execution.

A language gives the implementation of its instructions as a class,
LibraryInstruction, in its instruction library module, such as
Emplace_Bio·LibraryInstruction.py. An instance is made once for each journal, and
holds whatever the instructions build up between them. For each operation
specifier in the definition the class has a function of that name, given the
instruction's arguments by position:

  in       a copy of the value, so the function cannot change a variable
           through it
  out      an empty list, a box, to which the function appends the value
  in-out   a box holding a copy of the variable's value, which the function
           replaces

After each call, every box is to hold exactly one value of the format's
type; the interpreter takes the value out and keeps it as the variable's.
An empty box is evidence that the function wrote nothing, which no stand-in
value could be.

The function reports failure by raising an exception. LibraryInstruction can
also have finish(), called after the last instruction, and release(), called
at the end whatever happened. The functions are found by the operation
specifiers the definition lists, never by a name taken from the journal.

A descriptor an instruction writes to a variable is an open descriptor of the
interpreter's own. When the result holds it, it is sent to the gate beside
the result's bytes, and write_result closes it once sent; so release() is not
to close a descriptor it wrote.

This module is a library. An instruction language's interpreter program
calls interpret(), then write_result() for the result, then writes its
verdict; see Emplace_Bio·Interpreter.py.
"""

import copy ,os ,socket

import Journal
import Guard·WellFormed


def map__operation_function(language_definition ,library_instruction):
  """
  The function for each operation specifier of the definition, from the
  LibraryInstruction instance. Raises RuntimeError when one is missing.
  """
  map__function = {}
  for operation in language_definition.list__operation:
    function = getattr(library_instruction ,operation ,None)
    if not callable(function):
      raise RuntimeError(f"the language's LibraryInstruction has no function {operation}, which its definition lists")
    map__function[operation] = function
  return map__function

def interpret(journal_bytes ,language_definition ,library_instruction__module ,log ,constraint ,gate_invoking_account):
  """
  Given the encoded journal, the language definition, the language's
  instruction library module, log(tag ,message), the guard program, whose
  constraints the language reads for what execution needs, and the user name
  of account A. Returns (status ,result ,list__fd), where result is the
  encoded result record, or None when the journal declares no result, and
  list__fd is the descriptors the result holds, to be sent beside it. The
  status is 0 when the journal was played, 1 when execution failed, 2 when
  the journal could not be read or is not well formed, or the language
  cannot execute it.
  """
  try:
    data = Journal.decode(journal_bytes)
  except Journal.JournalError as error:
    log("journal-unreadable" ,str(error))
    return 2 ,None ,[]
  if not Guard·WellFormed.is__well_formed_journal(data ,language_definition ,log):
    return 2 ,None ,[]
  list__instruction_view = Guard·WellFormed.make__list__instruction_view(data ,language_definition)

  library_instruction = library_instruction__module.LibraryInstruction(constraint ,gate_invoking_account ,log)
  try:
    map__function = map__operation_function(language_definition ,library_instruction)
  except RuntimeError as error:
    log("cannot-execute" ,str(error))
    return 2 ,None ,[]

  map__value = {}   # variable name -> value
  where = "before the first instruction"
  try:
    for view in list__instruction_view:
      where = f"@{view.index} {view.operation}"
      list__value ,list__box = [] ,[]
      for argument ,(direction ,type_name) in zip(view.list__argument ,language_definition.format_of(view.operation)):
        if argument.is__literal():
          list__value.append(copy.deepcopy(argument.value))
        elif direction == "in":
          list__value.append(copy.deepcopy(map__value[argument.name]))
        else:
          box = [] if direction == "out" else [copy.deepcopy(map__value[argument.name])]
          list__value.append(box)
          list__box.append((argument.name ,type_name ,box))
      map__function[view.operation](*list__value)
      for name ,type_name ,box in list__box:
        if type(box) is not list or len(box) != 1:
          raise RuntimeError(f"the box for {name} holds {len(box) if type(box) is list else 'no list of'} values; it is to hold one")
        problem = language_definition.value_problem(box[0] ,type_name ,f"the value written to {name}")
        if problem:
          raise RuntimeError(problem)
        map__value[name] = copy.deepcopy(box[0])
    where = "after the last instruction"
    finish = getattr(library_instruction ,"finish" ,None)
    if callable(finish):
      finish()
  except Exception as error:
    log("execution-failed" ,f"{where}: {error}")
    return 1 ,None ,[]
  finally:
    release = getattr(library_instruction ,"release" ,None)
    if callable(release):
      try:
        release()
      except Exception as error:
        log("release-failed" ,str(error))

  if data["result"] is None:
    return 0 ,None ,[]
  result_type = dict(map(tuple ,data["list__variable"]))[data["result"]]
  marked ,list__fd = language_definition.descriptor_mark(map__value[data["result"]] ,result_type)
  return 0 ,Journal.encode_result(result_type ,marked) ,list__fd


# --------------------------------------------------------------------------------
# the result

RESULT_FD = 3

def write_result(result ,list__fd):
  """
  The encoded result, all of it, on descriptor 3, which is then closed, with
  the descriptors in list__fd sent beside its first bytes as SCM_RIGHTS, and
  closed once sent. The gate makes descriptor 3 a Unix socket; descriptors
  can travel no other way, so with any to send, a descriptor 3 that is not a
  socket raises OSError.
  """
  try:
    if not list__fd:
      view = memoryview(result)
      while view:
        view = view[os.write(RESULT_FD ,view):]
      os.close(RESULT_FD)
      return
    with socket.socket(fileno=RESULT_FD) as result_socket:    # closes descriptor 3 when done
      sent = socket.send_fds(result_socket ,[result] ,list__fd)
      result_socket.sendall(result[sent:])
  finally:
    for fd in list__fd:
      os.close(fd)
