"""Acceptance fixture for coverage_gap_scaffold.py (prompt #2).

`covered_add` has a test; `uncovered_format` deliberately does not.
"""


def covered_add(a, b):
    return a + b


def uncovered_format(email, is_admin, items, count):
    label = "admin" if is_admin else "user"
    if not items:
        return f"{label}:{email}:empty"
    return f"{label}:{email}:{len(items)}:{count}"


def uncovered_second(retries, timeout, label):
    if retries > 0:
        return f"{label}:{retries}:{timeout}"
    return "no-retries"


def uncovered_third(country, weight):
    if country == "US":
        return f"us:{weight}"
    return f"intl:{weight}"
