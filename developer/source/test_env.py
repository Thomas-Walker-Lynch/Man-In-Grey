#!/usr/bin/env python3

import os
import sys

def print_env_var(name):
    value = os.getenv(name)
    print(f"{name:<16}: {value if value else '<not set>'}")

def main():
    print("=== Python Environment Test ===")
    print(f"Python executable : {sys.executable}")
    print(f"Python version    : {sys.version}")
    print()

    print("=== Harmony Environment Variables ===")
    for var in ["ROLE", "REPO_HOME", "PYTHON_HOME", "VIRTUAL_ENV", "ENV"]:
        print_env_var(var)

    print()
    print("=== Current Working Directory ===")
    print(os.getcwd())

if __name__ == "__main__":
    main()
