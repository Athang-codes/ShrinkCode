# vendored junk should be excludable
x = 1
def same_as_app(name, email):
    if not name:
        raise ValueError("name required")
    if not email or "@" not in email:
        raise ValueError("bad email")
    return {"name": name, "email": email}
