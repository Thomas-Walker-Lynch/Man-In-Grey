# make/Harmony.mk - build *.lib.c and *.CLI.c
# written for the Harmony skeleton, always invoked from cwd  $REPO_HOME/<role>
# files have two suffixes by convention, e.g.: X.lib.c or Y.CLI.c 

.SUFFIXES:
.DELETE_ON_ERROR:

#--------------------------------------------------------------------------------
# Harmony structure

SHELL=/bin/bash

ECHO := printf "%b\n"

C_SOURCE_DIR     ?= authored
C                ?= gcc
CFLAGS           ?= -std=gnu11 -Wall -Wextra -Wpedantic -finput-charset=UTF-8
CFLAGS           += -MMD -MP
CFLAGS           += -include "$(REPO_HOME)/shared/tool/makefile/RT_global.h"
CFLAGS           += -I $(C_SOURCE_DIR)

# Project administrators can override this in their local makefile
LIBRARY_NAME     ?= $(PROJECT)
LIBRARY_NAME     := $(subst -,_,$(LIBRARY_NAME))

BUILD_DIR        ?= scratchpad/build
OBJECT_DIR       ?= $(BUILD_DIR)/object
LIBRARY_DIR      ?= scratchpad/made
MACHINE_DIR      ?= scratchpad/made

LIBRARY_FILE     ?= $(LIBRARY_DIR)/lib$(LIBRARY_NAME).a

# the project library is linked only when the namespace makes one
LN_FLAGS         ?= -L$(LIBRARY_DIR) -L/lib64 -L/lib $(if $(object_lib),-l$(LIBRARY_NAME))
# LN_FLAGS         ?= -L$(LIBRARY_DIR) -L/lib64 -L/lib -l$(LIBRARY_NAME)

KMOD_SOURCE_DIR  ?= authored
KMOD_CCFLAGS     ?= -I $(KMOD_SOURCE_DIR)
# Pass the global header to Kbuild exactly as done for user-space
KMOD_CCFLAGS     += -include $(REPO_HOME)/shared/tool/makefile/RT_global.h
KMOD_OUTPUT_DIR  ?= scratchpad/kmod

#--------------------------------------------------------------------------------
# derived variables

# source discovery (single dir)
c_source_lib  := $(wildcard $(C_SOURCE_DIR)/*.lib.c)
c_source_exec := $(wildcard $(C_SOURCE_DIR)/*.CLI.c)

# remove suffix to get base name
c_base_lib  := $(sort $(patsubst %.lib.c,%, $(notdir $(c_source_lib))))
c_base_exec := $(sort $(patsubst %.CLI.c,%, $(notdir $(c_source_exec))))

# two sets of object files, one for the lib, and one for the CLI programs
object_lib  := $(patsubst %, $(OBJECT_DIR)/%.lib.o, $(c_base_lib))
object_exec := $(patsubst %, $(OBJECT_DIR)/%.CLI.o, $(c_base_exec))

# executables are made from exec_ sources
exec_ := $(patsubst %, $(MACHINE_DIR)/%, $(c_base_exec))

#--------------------------------------------------------------------------------
# pull in dependencies

-include $(object_lib:.o=.d) $(object_exec:.o=.d)


#--------------------------------------------------------------------------------
# targets

# when no target is given make uses the first target, this one
.PHONY: usage
usage:
	@echo example usage: make clean
	@echo example usage: make library
	@echo example usage: make CLI
	@echo example usage: make library CLI

.PHONY: version
version:
	@echo makefile version 8.0
	if [ ! -z "$(C)" ]; then $(C) -v; fi
	/bin/make -v

.PHONY: information
information:
	@printf "· → Unicode middle dot - visible: [%b]\n" "·"
	@echo "C_SOURCE_DIR: " $(C_SOURCE_DIR)
	@echo "BUILD_DIR: " $(BUILD_DIR)
	@echo "c_source_lib: " $(c_source_lib)
	@echo "c_source_exec: " $(c_source_exec)
	@echo "c_base_lib: " $(c_base_lib)
	@echo "c_base_exec: " $(c_base_exec)
	@echo "object_lib: " $(object_lib)
	@echo "object_exec: " $(object_exec)
	@echo "exec_: " $(exec_)

.PHONY: library
library: $(LIBRARY_FILE)

$(LIBRARY_FILE): $(object_lib)
	@mkdir -p $(MACHINE_DIR)
	@if [ -s "$@" ] || [ -n "$(object_lib)" ]; then \
		echo "ar rcs $@ $^"; \
		ar rcs $@ $^; \
	else \
		rm -f "$@"; \
	fi   

#.PHONY: CLI
#CLI: $(LIBRARY_FILE) $(exec_)

.PHONY: CLI
CLI: library $(exec_)


# generally better to use the project local clean scripts, but this will make it so that the make targets can be run again

.PHONY: clean
clean:
	rm -f $(LIBRARY_FILE)
	for obj in $(object_lib) $(object_exec); do rm -f $$obj $${obj%.o}.d || true; done
	for i in $(exec_); do [ -e $$i ] && rm $$i || true; done
	rm -rf $(BUILD_DIR)


# recipes
#$(OBJECT_DIR)/%.o: $(C_SOURCE_DIR)/%.c
#	@mkdir -p $(OBJECT_DIR)
#	$(C) $(CFLAGS) $(CPPFLAGS) -o $@ -c $<

$(OBJECT_DIR)/%.o: $(C_SOURCE_DIR)/%.c
	@mkdir -p $(OBJECT_DIR)
	$(C) $(CFLAGS) $(if $(findstring .lib,$@),-D$(if $(NAMESPACE),$(NAMESPACE)·,)$(basename $*)) -o $@ -c $<

$(MACHINE_DIR)/%: $(OBJECT_DIR)/%.CLI.o
	@mkdir -p $(MACHINE_DIR)
	$(C) -o $@ $< $(LN_FLAGS)
