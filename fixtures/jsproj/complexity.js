// Hand-counted complexity: 2 ifs + 1 && + base = 4
function score(a, b) {
  if (a > 0 && b > 0) {
    return a + b;
  }
  if (a < 0) {
    return -a;
  }
  return 0;
}
