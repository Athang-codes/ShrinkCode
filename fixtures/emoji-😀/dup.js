// shrinkcode fixture: a renamed-variable duplicate pair, plus a non-ASCII
// function name, to exercise the analyzer bridge on a UTF-8 hostile code page.
function alpha(xs) {
  const out = [];
  for (const x of xs) {
    if (x > 0) {
      out.push(x * 2);
    }
  }
  return out;
}

function beta(ys) {
  const out = [];
  for (const y of ys) {
    if (y > 0) {
      out.push(y * 2);
    }
  }
  return out;
}

function 検証ユニット値(candidates) {
  const out = [];
  for (const c of candidates) {
    if (c > 0) {
      out.push(c * 2);
    }
  }
  return out;
}
