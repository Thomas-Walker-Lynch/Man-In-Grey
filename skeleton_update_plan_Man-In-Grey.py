# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
# The skeleton_update plan for Man-In-Grey: what is particular to this project
# when it is brought onto the Harmony skeleton.
#
# Two namespaces, because the build tool keys a namespace by the name before
# the dot: the Python orchestrator and its shell wrapper are copied, and the
# C gasket is compiled. Harmony.mk compiles *.CLI.c into a program named
# for the rest of the file name, so the gasket keeps its name,
# man_in_grey_apply.

MOVE = {
  "developer/source/Man_In_Grey": "developer/authored/Man_In_Grey.copy/Man_In_Grey",
  "developer/source/Man_In_Grey.py": "developer/authored/Man_In_Grey.copy/Man_In_Grey.py",
  "developer/source/Planner.py": "developer/authored/Man_In_Grey.copy/Planner.py",
  "developer/source/executor_inner.py": "developer/authored/Man_In_Grey.copy/executor_inner.py",
  "developer/source/executor_outer.py": "developer/authored/Man_In_Grey.copy/executor_outer.py",
  "developer/source/diag_perm": "developer/authored/Man_In_Grey.copy/diag_perm",
  "developer/source/Man_In_Grey_apply.c": "developer/authored/Man_In_Grey_apply.make/man_in_grey_apply.CLI.c",
  "developer/source/todo.txt": "developer/document/todo.txt",
  "tester/test_0/": "tester/authored/test_0/",
}

# Harmony has these places, but the files are replaced by its tools: setup
# replaces the env scripts, build and promote replace compile, release and
# clean_release, and the .org documents are the old Harmony's.
DEPRECATE = (
  "developer/tool/clean_release",
  "developer/tool/compile",
  "developer/tool/env",
  "developer/tool/release",
  "tester/tool/env",
  "document/Workflow.org",
  "document/environment_guide.org",
  "document/general_info.org",
)

# release/ holds copies made by developer/tool/release.
DUPLICATE = (
  "release/",
)

KEEP = ()

# Scripts that were never executable in git; developer/tool/release gave
# them their mode when it installed them.
EXECUTABLE = (
  "developer/authored/Man_In_Grey.copy/Man_In_Grey",
  "developer/authored/Man_In_Grey.copy/Man_In_Grey.py",
  "developer/authored/Man_In_Grey.copy/diag_perm",
  "developer/authored/Man_In_Grey.copy/executor_inner.py",
)
