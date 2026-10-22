# make/target_kernel-module.mk — build *.kmod.c as kernel modules (single-pass, kmod-only)
# invoked from $REPO_HOME/<role>
# version 1.4

.SUFFIXES:
.DELETE_ON_ERROR:

#--------------------------------------------------------------------------------
# defaults for environment variables (override from outer make/env as needed)

# Kernel build tree, which is part of the Linux system, use running kernel if unset
KMOD_BUILD_DIR  ?= /lib/modules/$(shell uname -r)/build

# Authored source directory (single dir)
KMOD_SOURCE_DIR ?= cc

# Extra compiler flags passed to Kbuild (e.g., -I $(KMOD_SOURCE_DIR))
KMOD_CCFLAGS ?= 

# Include *.lib.c into modules (1=yes, 0=no)
KMOD_INCLUDE_LIB ?= 1

# KMOD_OUTPUT_DIR is constrained, relative path, on the scratchpad, and ends in kmod
# Require: non-empty, relative, no '..', ends with 'kmod' dir
define assert_kmod_output_dir_ok
  $(if $(strip $(1)),,$(error KMOD_OUTPUT_DIR is empty))
  $(if $(filter /%,$(1)),$(error KMOD_OUTPUT_DIR must be relative: '$(1)'),)
  $(if $(filter %/../% ../% %/.. ..,$(1)),$(error KMOD_OUTPUT_DIR must not contain '..': '$(1)'),)
  $(if $(filter %/kmod %/kmod/ kmod,$(1)),,$(error KMOD_OUTPUT_DIR must end with 'kmod': '$(1)'))
endef
KMOD_OUTPUT_DIR ?= scratchpad/kmod
$(eval $(call assert_kmod_output_dir_ok,$(KMOD_OUTPUT_DIR)))

# The kernel make needs and absolute path to find the output directory
ABS_KMOD_OUTPUT_DIR := $(CURDIR)/$(KMOD_OUTPUT_DIR)

#--------------------------------------------------------------------------------
# derived variables (computed from the above)

# Authored basenames (without suffix)
base_list := $(patsubst %.kmod.c,%,$(notdir $(wildcard $(KMOD_SOURCE_DIR)/*.kmod.c)))

# Optional library sources (without suffix) to include inside modules
ifeq ($(KMOD_INCLUDE_LIB),1)
lib_base := $(patsubst %.lib.c,%,$(notdir $(wildcard $(KMOD_SOURCE_DIR)/*.lib.c)))
else
lib_base :=
endif

# Staged sources (kept namespaced to prevent .o collisions)
all_kmod_c := $(addsuffix .kmod.c,$(addprefix $(KMOD_OUTPUT_DIR)/,$(base_list)))
all_lib_c  := $(addsuffix .lib.c,$(addprefix $(KMOD_OUTPUT_DIR)/,$(lib_base)))



#--------------------------------------------------------------------------------
# targets

.PHONY: usage
usage:
	@printf "Usage: make [kmod|clean|information|version]\n"

.PHONY: version
version:
	@echo target_kmod version 1.4

.PHONY: information
information:
	@echo "KMOD_SOURCE_DIR:   " $(KMOD_SOURCE_DIR)
	@echo "KMOD_BUILD_DIR:    " $(KMOD_BUILD_DIR)
	@echo "KMOD_OUTPUT_DIR:   " $(KMOD_OUTPUT_DIR)
	@echo "base_list:    " $(base_list)
	@echo "lib_base:     " $(lib_base)
	@echo "all_kmod_c:   " $(all_kmod_c)
	@echo "all_lib_c:    " $(all_lib_c)
	@echo "KMOD_INCLUDE_LIB=" $(KMOD_INCLUDE_LIB)


ifeq ($(strip $(base_list)),)
  $(warning No *.kmod.c found under $(KMOD_SOURCE_DIR); nothing to build)
endif

# --- Parallel-safe preparation as real targets ---

# ensure the staging dir exists (order-only prereq)
$(KMOD_OUTPUT_DIR):
	@mkdir -p "$(KMOD_OUTPUT_DIR)"

# generate the Kbuild control Makefile
$(KMOD_OUTPUT_DIR)/Makefile: | $(KMOD_OUTPUT_DIR)
	@{ \
	  printf "ccflags-y += %s\n" "$(KMOD_CCFLAGS)"; \
	  printf "obj-m := %s\n" "$(foreach m,$(base_list),$(m).o)"; \
	  for m in $(base_list); do \
	    printf "%s-objs := %s.kmod.o" "$$m" "$$m"; \
	    for lb in $(lib_base); do printf " %s.lib.o" "$$lb"; done; \
	    printf "\n"; \
	  done; \
	} > "$@"

# stage kmod sources (one rule per file; parallelizable)
$(KMOD_OUTPUT_DIR)/%.kmod.c: $(KMOD_SOURCE_DIR)/%.kmod.c | $(KMOD_OUTPUT_DIR)
	@echo "--- Stage: $@ ---"
	@cp -f "$(abspath $<)" "$@"

# stage library sources (optional; also parallelizable)
$(KMOD_OUTPUT_DIR)/%.lib.c: $(KMOD_SOURCE_DIR)/%.lib.c | $(KMOD_OUTPUT_DIR)
	@echo "--- Stage: $@ ---"
	@cp -f "$(abspath $<)" "$@"


.PHONY: kmod
kmod: $(KMOD_OUTPUT_DIR)/Makefile $(all_kmod_c) $(all_lib_c)
ifeq ($(strip $(base_list)),)
	@echo "--- No kmod sources; nothing to do ---"
else
	@echo "--- Invoking Kbuild for kmod: $(base_list) ---"
	$(MAKE) -C "$(KMOD_BUILD_DIR)" M="$(ABS_KMOD_OUTPUT_DIR)" modules
endif

# quality-of-life: allow 'make scratchpad/kmod/foo.ko' after batch build
$(KMOD_OUTPUT_DIR)/%.ko: kmod
	@true

.PHONY: clean
clean:
	@echo "Cleaning: $(KMOD_BUILD_DIR)"
	@$(MAKE) -C "$(KMOD_BUILD_DIR)" M="$(ABS_KMOD_OUTPUT_DIR)" clean >/dev/null 2>&1 || true
	@echo "Cleaning: $(KMOD_OUTPUT_DIR)"
	@rm -rf -- "$(KMOD_OUTPUT_DIR)"
