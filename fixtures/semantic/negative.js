// Negative control for shrinkcode prompt #4: functions of deliberately similar
// length and shape that do genuinely different things. They must NOT cluster
// under --canonicalize — a false match here could lead to an incorrect merge,
// so this file is as important as positive.js.

// ~6 non-blank lines, loop + accumulator: sums prices
export function cartTotal(cart, rate) {
  let total = 0;
  for (const item of cart.items) {
    total += item.price * (1 - rate);
  }
  return total;
}

// ~6 non-blank lines, split + map + join: builds display initials
export function nameBadge(user, theme) {
  const words = user.name.split(" ");
  const initials = words.map((w) => w.charAt(0)).join("");
  return initials.length ? `${theme}: ${initials}` : user.name;
}

// ~6 non-blank lines, string + loop: escapes a query string
export function escapeQuery(raw, limit) {
  let safe = "";
  for (const ch of raw) {
    safe += ch === '"' ? '\\"' : ch;
  }
  return safe.slice(0, limit);
}
