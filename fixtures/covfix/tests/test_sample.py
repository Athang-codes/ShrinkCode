"""Only covers covered_add — the scaffold must find the other gap."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sample import covered_add, uncovered_format, uncovered_second, uncovered_third


def test_covered_add():
    assert covered_add(2, 3) == 5


def test_uncovered_format_now_covered():
    # added by the verification run: this function now has a real test, so the
    # scaffold must drop it from the generated stub (shrink)
    assert uncovered_format("a@b.com", True, [], 0) == "admin:a@b.com:empty"
    assert uncovered_format("a@b.com", False, [1, 2], 5) == "user:a@b.com:2:5"


def test_uncovered_second_now_covered():
    assert uncovered_second(3, 30, "job") == "job:3:30"
    assert uncovered_second(0, 30, "job") == "no-retries"


def test_uncovered_third_now_covered():
    assert uncovered_third("US", 2) == "us:2"
    assert uncovered_third("DE", 2) == "intl:2"
