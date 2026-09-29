// Guards for shrinkcode prompt #4: cases the deep pass must NOT merge even
// though the default structural pass does. A deep-scan hit can lead to a merge,
// so these are the differences worth paying recall for.

// guard 1: identical shape, different member name — `.id` is not `.name`
export function labelById(record) {
  const parts = [];
  parts.push(record.id);
  parts.push(record.id.toUpperCase());
  return parts.join("-");
}

export function labelByName(record) {
  const parts = [];
  parts.push(record.name);
  parts.push(record.name.toUpperCase());
  return parts.join("-");
}

// guard 2: identical shape, different operator — `a - b` is not `a + b`
export function shiftDown(base, delta) {
  const total = base - delta;
  const doubled = total - delta;
  return doubled * 2;
}

export function shiftUp(base, delta) {
  const total = base + delta;
  const doubled = total + delta;
  return doubled * 2;
}
