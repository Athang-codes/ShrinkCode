import os

def validate_user(name, email):
    if not name:
        raise ValueError("name required")
    if not email or "@" not in email:
        raise ValueError("bad email")
    return {"name": name, "email": email}

def validate_admin(name, email):
    if not name:
        raise ValueError("name required")
    if not email or "@" not in email:
        raise ValueError("bad email")
    return {"name": name, "email": email, "admin": True}

# comment line
RESULT = []
for i in range(3):
    if i % 2 == 0:
        RESULT.append(i)
