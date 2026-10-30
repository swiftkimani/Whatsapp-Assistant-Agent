#!/usr/bin/env python3
"""Print an argon2id hash to use as DASHBOARD_PASSWORD_HASH.

    python scripts/hash_password.py

Needed once the dashboard is reachable from anywhere but this machine: the hash
is the only form of the password that survives someone reading the environment.
The password is typed, not passed as an argument, so it stays out of your shell
history and out of the process list.

Paste the output into Coolify's environment variables (or .env) as
DASHBOARD_PASSWORD_HASH, and remove DASHBOARD_PASSWORD.
"""
import getpass
import sys

from argon2 import PasswordHasher

MIN_LENGTH = 12


def main() -> int:
    password = getpass.getpass("Dashboard password: ")
    if len(password) < MIN_LENGTH:
        print(f"Use at least {MIN_LENGTH} characters.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Again: "):
        print("Those don't match.", file=sys.stderr)
        return 1
    print(PasswordHasher().hash(password))
    return 0


if __name__ == "__main__":
    sys.exit(main())
