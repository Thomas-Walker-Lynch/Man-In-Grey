# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
journal_interpreter - the general journal interpreter of Man-In-Grey.

A bespoke journal interpreter is a gate, a guard and this general
interpreter. The bespoke interpreter chooses the command language and the
constraints, and calls interpret(). interpret() decodes the journal, runs the
language's checks in order, the guard among them, and executes the journal
only when every check finds nothing wrong. A check that finds problems lists
them all, and the journal is refused whole.

This module is a library; it is not run by itself.
"""

import sys

import Journal

# the checks a run can stop after, in the order they run
STOP = ("decode" ,"wellformed" ,"constraint" ,"validity" ,"filesystem")


def interpret(journal_bytes ,language ,constraint ,caller ,stop_after=None ,print_journal=False ,out=None):
  """
  Given the encoded journal, the command language module, the constraints,
  and the caller's account name. Returns a process exit status: 0 when the
  journal was executed, or when the run stopped as asked after a check that
  passed; 1 when a check refused the journal or execution failed; 2 when the
  journal could not be read.
  """
  out = out or sys.stdout
  try:
    data = Journal.decode(journal_bytes)
  except Journal.JournalError as error:
    print(f"error: {error}" ,file=out)
    return 2
  if data["command_language"] != language.NAME:
    print(f"error: the journal is in the command language {data['command_language']!r};"
          f" this interpreter accepts {language.NAME!r}" ,file=out)
    return 1

  if print_journal:
    for index ,command in enumerate(data["command_list"]):
      print(Journal.command_line(index ,command) ,file=out)
  if stop_after == "decode":
    return 0

  for name ,check in language.CHECK:
    problem_list = check(data ,constraint ,caller)
    if problem_list:
      print(f"{name}: refused, {len(problem_list)} problem{'s' if len(problem_list) != 1 else ''}" ,file=out)
      for problem in problem_list:
        print(f"  ! {problem}" ,file=out)
      return 1
    if stop_after == name:
      print(f"{name}: OK" ,file=out)
      return 0

  return language.execute(data ,lambda line: print(f"  {line}" ,file=out))
