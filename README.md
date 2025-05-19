# Harmony

**Status:** Source-visible only — not open source.

This repository contains internal development tools, Python environments, and structured workspaces for role-based computation and testing. It reflects standardized RT project conventions for environment entry, tool layering, and reproducible developer/tester workflows.

## Licensing

This project is *not* open source.

The source code is visible for collaboration, transparency, and historical record only. No permission is granted to use, modify, copy, or redistribute any part of the codebase.

See the [`LICENSE`](./LICENSE) file for details.

## Roles

This repository is structured around the following roles:
- `developer/` — implementation and code testing
- `tester/` — validation and reproducibility
- `tool_shared/` — shared tools, environments, and third-party modules

Each role is entered via its respective `env_<role>` script.


