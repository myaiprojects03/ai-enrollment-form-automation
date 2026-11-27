"""Make a review console account entry for STAFF_ACCOUNTS.

    python -m scripts.staff reviewer@example.com

Asks for the password twice and prints the line to add (comma-separated if there are several reviewers).
The password itself is never stored.
"""
import getpass
import sys

from app.security.staff import hash_password

if __name__ == "__main__":
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        sys.exit("usage: python -m scripts.staff reviewer@example.com")
    first = getpass.getpass("Password (12 characters or more): ")
    if len(first) < 12:
        sys.exit("Use at least 12 characters.")
    if getpass.getpass("Same again: ") != first:
        sys.exit("The two passwords differ.")
    print(f"{sys.argv[1].lower()}:{hash_password(first)}")
