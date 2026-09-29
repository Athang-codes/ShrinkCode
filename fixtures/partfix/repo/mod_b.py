"""Module B — no imports from the other modules (deliberately independent)."""


def _clamp_low(value, floor):
    if value is None:
        return floor
    number = float(value)
    if number < floor:
        return floor
    return number


def _clamp_hi(value, floor):
    if value is None:
        return floor
    number = float(value)
    if number < floor:
        return floor
    return number


def floor_of(value):
    return _clamp_low(value, 0)


def floor_of_alt(value):
    return _clamp_hi(value, 0)
