"""Module A — no imports from the other modules (deliberately independent)."""


def _format_pair(label, value):
    if value is None:
        return f"{label}: none"
    text = str(value).strip()
    if not text:
        return f"{label}: none"
    return f"{label}: {text}"


def _render_pair(label, value):
    if value is None:
        return f"{label}: none"
    text = str(value).strip()
    if not text:
        return f"{label}: none"
    return f"{label}: {text}"


def describe(name, value):
    return _format_pair(name, value)


def describe_alt(name, value):
    return _render_pair(name, value)
