// Structural twins: identical validation logic, completely different names.
function validateUser(name, email) {
  if (!name) {
    throw new Error("name required");
  }
  if (!email || !email.includes("@")) {
    throw new Error("bad email");
  }
  return { name: name, email: email };
}

function checkAdministrator(person, address) {
  if (!person) {
    throw new Error("name required");
  }
  if (!address || !address.includes("@")) {
    throw new Error("bad email");
  }
  return { name: person, email: address };
}
