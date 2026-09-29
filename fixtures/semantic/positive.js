// Acceptance fixture for shrinkcode prompt #4 (semantic / canonicalized scan).
// Every pair in this file is the SAME computation written two different ways:
// reordered independent checks, a for-of loop vs. an array pipeline. The deep
// pass (--canonicalize) must place each pair in one cluster; the default
// structural pass is not expected to.

// --- pair 1: identical validation, independent checks written in another order

export function isValidSignupA(email, age) {
  const addr = email.trim();
  if (!addr) return false;
  if (addr.length > 120) return false;
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(addr)) return false;
  if (age < 13) return false;
  return true;
}

export function isValidSignupB(value, years) {
  const s = value.trim();
  if (years < 13) return false;
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s)) return false;
  if (s.length > 120) return false;
  if (!s) return false;
  return true;
}

// --- pair 2: explicit for-of loop vs. filter().map() pipeline

export function activeEmailsLoop(users) {
  const out = [];
  for (const u of users) {
    if (u.active) {
      out.push(u.email);
    }
  }
  return out;
}

export function activeEmailsChain(list) {
  // same result, expressed with the array pipeline instead of an explicit loop
  return list
    .filter((u) => u.active)
    .map((u) => u.email);
}

// --- pair 3: loop vs. map() with different variable names in both

export function trimmedLoop(names) {
  const kept = [];
  for (const n of names) kept.push(n.trim());
  return kept;
}

export function trimmedChain(labels) {
  // trailing comment lines keep this fixture above the default --min-lines 5
  // without changing what the function computes
  return labels.map((l) => l.trim());
}
