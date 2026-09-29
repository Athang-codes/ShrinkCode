// Known boundary of the deep pass, kept as a fixture so the limitation stays
// measured instead of assumed: the canonicalization strips literal *values*
// (a regex, a string, a number all become REGEX/STR/NUM), so two validators
// that share a shape but enforce different rules still cluster. That is
// deliberate — it is what lets "same logic, different constant" copies match —
// but it means a deep-scan hit on validation code always needs the constants
// checked by a human before anything is merged.

export function isValidPhone(value) {
  const digits = value.replace(/\D/g, "");
  if (!digits) return false;
  if (digits.length !== 10) return false;
  return true;
}

export function isValidHexColor(value) {
  const body = value.replace(/^#/, "");
  if (!body) return false;
  if (body.length !== 6) return false;
  return true;
}
