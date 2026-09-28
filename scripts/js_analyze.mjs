#!/usr/bin/env node
/**
 * js_analyze.mjs — first-class duplicate + complexity detection for
 * JS/TS/JSX/TSX, giving these languages the same treatment
 * complexity_report.py gives Python.
 *
 * Duplicates: every function/block is normalized — identifiers replaced
 * with positional placeholders ($1, $2, ...), literals stripped — then
 * hashed. Blocks sharing a hash are *structural* duplicates: this catches
 * renamed-variable copies that find_duplicates.py's text comparison only
 * flags as near-duplicates (lower confidence) at best. Near mode compares
 * normalized token sequences with a difflib-style ratio.
 *
 * --canonicalize is the opt-in deep-scan mode: on top of the above it also
 * normalizes the ways logically-identical code is spelled differently —
 * commutative operand order (`a && b` == `b && a`), symmetric comparisons
 * (`x === null` == `null === x`), the order of *independent* statements in a
 * block, and the loop/form spelling of a collection pipeline
 * (`for (const x of xs) out.push(f(x))` == `xs.map(f)`). It is deliberately
 * slower and deliberately stricter (member/property names and scalar
 * operators are kept, so `.id` never looks like `.name`), and it stays a
 * candidate generator: every hit still needs a human plus a characterization
 * test before anything is merged.
 *
 * Complexity: 1 + decision points per function (if, for/for-in/for-of,
 * while, do-while, catch, &&/||/??, ternary, non-default switch case) —
 * the same formula complexity_report.py uses for Python, so the two
 * numbers are comparable in a mixed-language codebase.
 *
 * Output: JSON on stdout, shaped to merge with the Python scripts:
 *   - duplicates: {exact_clusters: [[{path,line}]], near_pairs: [{ratio,a,b}]}
 *   - complexity: {per_function: [{file,function,line,complexity}], totals:{...}}
 * (complexity's shape matches complexity_report.py --save exactly, so
 *  --save/--diff snapshots are interchangeable between the two.)
 *
 * Usage:
 *   node js_analyze.mjs <path> [--mode all|duplicates|complexity]
 *        [--min-lines 5] [--similarity 0.85] [--top 25]
 *        [--save out.json] [--diff baseline.json] [--canonicalize]
 *
 * Dependencies: @babel/parser + @babel/traverse only. If they aren't
 * resolvable, this script prints how to install them and exits nonzero
 * (the Python scripts turn that into a friendly hint, not a crash).
 */

import { createHash } from "node:crypto";
import { readFileSync, statSync, readdirSync, existsSync, writeFileSync } from "node:fs";
import { dirname, join, extname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import process from "node:process";

const KNOWN_MODES = new Set(["all", "duplicates", "complexity", "functions"]);

function fail(msg) {
  process.stderr.write(`js_analyze.mjs: ${msg}\n`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// shrinkcode.config.json discovery (equivalent to scripts/shrinkcode_config.py:
// target root, walk up <=3 levels, merge over built-in defaults; optional —
// every behavior works with no config file present, exactly as before)
// ---------------------------------------------------------------------------

function findConfig(startPath) {
  let cur = startPath;
  try { if (statSync(cur).isFile()) cur = dirname(cur); } catch { /* keep */ }
  for (let i = 0; i <= 3; i++) {
    const candidate = join(cur, "shrinkcode.config.json");
    if (existsSync(candidate)) return candidate;
    const parent = dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return null;
}

function loadConfig(startPath) {
  const defaults = { excludePaths: [], duplication: { minLines: null, similarity: null } };
  const cfgPath = findConfig(startPath);
  if (!cfgPath) return defaults;
  try {
    const data = JSON.parse(readFileSync(cfgPath, "utf-8"));
    const out = {
      excludePaths: Array.isArray(data.excludePaths) ? data.excludePaths : [],
      duplication: {
        minLines: data.duplication?.minLines ?? null,
        similarity: data.duplication?.similarity ?? null,
      },
    };
    return out;
  } catch (e) {
    process.stderr.write(`js_analyze.mjs: ignoring unreadable config ${cfgPath}: ${e.message}\n`);
    return defaults;
  }
}

function matchesExclude(relPath, patterns) {
  if (!patterns || patterns.length === 0) return false;
  const norm = relPath.replace(/\\/g, "/").replace(/^\.\//, "");
  const segs = norm.split("/");
  for (let pat of patterns) {
    pat = pat.replace(/\\/g, "/").replace(/^\.\//, "");
    // fnmatch-style: ** crosses separators, * does not
    const rx = new RegExp(
      "^" + pat.replace(/[.+^${}()|[\]\\]/g, "\\$&")
        .split("**").join("\u0000")
        .split("*").join("[^/]*")
        .split("\u0000").join(".*")
      + "$"
    );
    if (rx.test(norm)) return true;
    if (pat.endsWith("/**") && (norm === pat.slice(0, -3) || norm.startsWith(pat.slice(0, -2)))) return true;
    if (!pat.includes("/") && !pat.includes("*") && segs.includes(pat)) return true;
  }
  return false;
}

function printUsageAndExit() {
  process.stdout.write(
    "Usage: node js_analyze.mjs <path> [--mode all|duplicates|complexity|functions]\n" +
    "       [--min-lines 5] [--similarity 0.85] [--top 25] [--save out.json]\n" +
    "       [--diff baseline.json] [--canonicalize] [--max-compare 4000]\n\n" +
    "  --canonicalize  opt-in deep pass: also folds commutative operand order,\n" +
    "                  symmetric comparisons, independent-statement order and\n" +
    "                  loop-vs-array-chain spelling before fingerprinting.\n" +
    "                  Slower, stricter, and still candidates-not-verdicts.\n"
  );
  process.exit(0);
}

function parseArgs(argv) {
  const args = {
    path: null, mode: "all", minLines: null, similarity: null, top: 25,
    save: null, diff: null, canonicalize: false, maxCompare: 4000,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const need = () => {
      if (i + 1 >= argv.length) fail(`missing value for ${a}`);
      return argv[++i];
    };
    if (a === "--mode") { args.mode = need(); if (!KNOWN_MODES.has(args.mode)) fail(`unknown --mode ${args.mode}`); }
    else if (a === "--min-lines") args.minLines = parseInt(need(), 10);
    else if (a === "--similarity") args.similarity = parseFloat(need());
    else if (a === "--top") args.top = parseInt(need(), 10);
    else if (a === "--save") args.save = need();
    else if (a === "--diff") args.diff = need();
    else if (a === "--max-compare") args.maxCompare = parseInt(need(), 10);
    else if (a === "--canonicalize") args.canonicalize = true;
    else if (a === "--help" || a === "-h") printUsageAndExit();
    else if (a.startsWith("-")) fail(`unknown flag ${a}`);
    else if (args.path === null) args.path = a;
    else fail(`unexpected argument ${a}`);
  }
  if (args.path === null) printUsageAndExit();
  return args;
}

// ---------------------------------------------------------------------------
// dependency loading — graceful, never a raw stack trace for missing deps
// ---------------------------------------------------------------------------

async function loadBabel() {
  const here = dirname(fileURLToPath(import.meta.url));
  const candidates = [join(here, "..", "node_modules"), join(here, "node_modules")];
  let parse = null, traverse = null;
  const pick = (mod, name) => {
    // CJS-transpiled packages expose the function differently depending on
    // how Node links them: named export, default, or default.<name>
    if (typeof mod?.[name] === "function") return mod[name];
    if (typeof mod?.default === "function") return mod.default;
    if (typeof mod?.default?.[name] === "function") return mod.default[name];
    return null;
  };
  for (const base of candidates) {
    if (!existsSync(base)) continue;
    try {
      parse = pick(await import(pathToFileURL(join(base, "@babel", "parser", "lib", "index.js")).href), "parse");
      traverse = pick(await import(pathToFileURL(join(base, "@babel", "traverse", "lib", "index.js")).href), "traverse");
      if (parse && traverse) break;
    } catch { /* try next candidate */ }
  }
  if (!parse || !traverse) {
    try {
      const p = await import("@babel/parser");
      const t = await import("@babel/traverse");
      parse = parse || pick(p, "parse");
      traverse = traverse || pick(t, "traverse");
    } catch { /* fall through to fail() below */ }
  }
  if (!parse || !traverse) {
    fail(
      "cannot resolve @babel/parser / @babel/traverse.\n" +
      "  Install once with:  npm install @babel/parser @babel/traverse\n" +
      "  (inside the shrinkcode skill folder), or run via\n" +
      "  npx --yes -p @babel/parser -p @babel/traverse node js_analyze.mjs <path>"
    );
  }
  return { parse, traverse };
}

// ---------------------------------------------------------------------------
// file walking
// ---------------------------------------------------------------------------

const JS_EXTS = new Set([".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"]);
const SKIP_DIRS = new Set(["node_modules", ".git", "dist", "build", ".next", "__pycache__", ".venv", "venv", "coverage", ".turbo", "out"]);

function iterFiles(root) {
  const out = [];
  const st = statSync(root, { throwIfNoEntry: false });
  if (!st) return out;
  if (st.isFile()) {
    if (JS_EXTS.has(extname(root))) out.push(root);
    return out;
  }
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (!SKIP_DIRS.has(entry.name) && !entry.name.startsWith(".")) walk(join(dir, entry.name));
      } else if (JS_EXTS.has(extname(entry.name))) {
        out.push(join(dir, entry.name));
      }
    }
  };
  walk(root);
  return out;
}

// ---------------------------------------------------------------------------
// structural normalization -- identifiers become positional placeholders,
// literals stripped; optional --canonicalize sorts commutative operands
// ---------------------------------------------------------------------------

const IGNORED_KEYS = new Set([
  "start", "end", "loc", "range", "extra", "leadingComments",
  "trailingComments", "innerComments", "comments", "tokens",
]);

function serializeNode(node, idMap, opts) {
  if (node === null || node === undefined) return "";
  if (Array.isArray(node)) {
    return "[" + node.map((n) => serializeNode(n, idMap, opts)).join(",") + "]";
  }
  if (typeof node !== "object") return JSON.stringify(node);

  // --canonicalize synthesizes these two pseudo-nodes: CanonicalBody carries
  // the statement-order-canonicalized body text (see canonicalBodyText), and
  // CanonicalProp marks a member name (`x.id`) as a name rather than a
  // variable reference
  if (node.type === "CanonicalBody") return node.text;
  if (node.type === "CanonicalProp") return "P:" + node.name;

  if (node.type === "Identifier" || node.type === "JSXIdentifier") {
    if (!idMap.has(node.name)) idMap.set(node.name, "$" + (idMap.size + 1));
    return "Id(" + idMap.get(node.name) + ")";
  }

  // Non-computed property/method keys are *names*, not variable references:
  // keep them literal so `{name: name}` in one function can match
  // `{name: otherVar}` in a renamed copy (positional placeholders for keys
  // would desync the map when the same word appears as key in one function
  // and as a fresh identifier in its twin).
  const isPropLike =
    (node.type === "ObjectProperty" || node.type === "ClassProperty" ||
     node.type === "ClassMethod" || node.type === "ObjectMethod" ||
     node.type === "ClassPrivateMethod") &&
    node.key && !node.computed;
  if (isPropLike) {
    const keyTok = node.key.type === "Identifier"
      ? "K:" + node.key.name
      : "K:" + serializeNode(node.key, idMap, opts);
    const rest = { ...node, key: undefined };
    delete rest.key;
    const restKeys = Object.keys(rest)
      .filter((k) => !IGNORED_KEYS.has(k) && k !== "type" && rest[k] !== undefined)
      .sort()
      .map((k) => {
        const v = rest[k];
        if (v && typeof v === "object") return k + "=" + serializeNode(v, idMap, opts);
        return scalarProp(k, v, opts);
      })
      .filter(Boolean);
    return node.type + "{key=" + keyTok + (restKeys.length ? "," + restKeys.join(",") : "") + "}";
  }

  switch (node.type) {
    case "StringLiteral": return "STR";
    case "NumericLiteral": case "BigIntLiteral": case "DecimalLiteral": return "NUM";
    case "BooleanLiteral": return "BOOL";
    case "NullLiteral": return "NULL";
    case "RegExpLiteral": return "REGEX";
    case "TemplateLiteral": return "TEMPLATE";
  }

  if (opts.canonicalize) {
    // A member name is a name, not a variable reference: keeping it means a deep
    // scan never reports `x.id` and `x.name` as the same piece of code (the
    // default pass collapses both to a positional placeholder).
    if ((node.type === "MemberExpression" || node.type === "OptionalMemberExpression") &&
        !node.computed && node.property && node.property.type === "Identifier") {
      node = { ...node, property: { type: "CanonicalProp", name: node.property.name } };
    }
    // `xs.map(f)` / `xs.filter(f).map(g)` fold into the same marker the
    // equivalent for-of loop produces (see collapseAccumulatorTail), so the two
    // spellings of one pipeline fingerprint identically.
    if (node.type === "CallExpression") {
      const chain = canonChainText(node, opts);
      if (chain !== null) return chain;
    }
  }

  // --canonicalize: sort operands of commutative logical operators so
  // `a && b` and `b && a` fingerprint identically
  if (opts.canonicalize && node.type === "LogicalExpression" &&
      ["&&", "||", "??"].includes(node.operator)) {
    const flat = [];
    const flatten = (n) => {
      if (n.type === "LogicalExpression" && n.operator === node.operator) {
        flatten(n.left); flatten(n.right);
      } else flat.push(n);
    };
    flatten(node);
    const parts = flat.map((n) => serializeNode(n, idMap, opts)).sort();
    return "Log(" + node.operator + "[" + parts.join(",") + "])";
  }

  // --canonicalize: ==/===/!=/!== are symmetric, so `null === x` (Yoda style)
  // and `x === null` must fingerprint identically
  if (opts.canonicalize && node.type === "BinaryExpression" &&
      ["==", "===", "!=", "!=="].includes(node.operator)) {
    const parts = [serializeNode(node.left, idMap, opts),
                   serializeNode(node.right, idMap, opts)].sort();
    return "Bin(" + node.operator + "[" + parts.join(",") + "])";
  }

  const keys = Object.keys(node).filter((k) => !IGNORED_KEYS.has(k) && k !== "type").sort();
  const parts = keys.map((k) => {
    const v = node[k];
    if (v && typeof v === "object") return k + "=" + serializeNode(v, idMap, opts);
    return scalarProp(k, v, opts);
  }).filter(Boolean);
  return node.type + "{" + parts.join(",") + "}";
}

function fingerprint(tokens) {
  return createHash("sha1").update(tokens.join(" ")).digest("hex");
}

// Scalar node properties (`operator`, `kind`, `computed`, `optional`, ...) are
// dropped by the default pass — it compares shape, not spelling. The deep pass
// keeps them, because `a - b` and `a + b` are not the same code and, in a pass
// whose hits may lead to a merge, a false positive costs more than a miss.
function scalarProp(key, value, opts) {
  if (!opts.canonicalize) return null;
  const t = typeof value;
  if (t === "string" || t === "boolean" || t === "number") {
    return key + "=" + JSON.stringify(value);
  }
  return null;
}

// ---------------------------------------------------------------------------
// --canonicalize: pipeline folding + statement-order canonicalization
//
// Opt-in only. Default mode has to stay byte-identical to what it always
// produced, so every helper here is reached exclusively behind
// `opts.canonicalize`.
// ---------------------------------------------------------------------------

const ELEM_TOK = "#E"; // canonical placeholder for a loop/arrow element binding

function freshIdMap(seed) {
  const map = new Map();
  if (seed) for (const name of Object.keys(seed)) map.set(name, seed[name]);
  return map;
}

// Serialize one expression with its OWN identifier map, so its text doesn't
// depend on which statement it sits in — that is what makes a statement
// comparable between two copies that list their statements in another order.
function canonExpr(node, opts, seed) {
  return serializeNode(node, freshIdMap(seed), opts);
}

function blockStatements(node) {
  if (!node) return [];
  return node.type === "BlockStatement" ? node.body : [node];
}

// `x => X` / `{ return X; }` -> {param, body}; fancier callbacks don't fold
function callbackBody(fn) {
  if (!fn || (fn.type !== "ArrowFunctionExpression" && fn.type !== "FunctionExpression")) return null;
  if (fn.params.length !== 1 || fn.params[0].type !== "Identifier") return null;
  if (fn.type === "ArrowFunctionExpression" && fn.body.type !== "BlockStatement") {
    return { param: fn.params[0].name, body: fn.body };
  }
  const stmts = blockStatements(fn.body);
  if (stmts.length === 1 && stmts[0].type === "ReturnStatement" && stmts[0].argument) {
    return { param: fn.params[0].name, body: stmts[0].argument };
  }
  return null;
}

// `<expr>.map(fn)` / `<expr>.filter(fn)` with a single simple callback
function chainCall(node) {
  if (!node || node.type !== "CallExpression" || node.arguments.length !== 1) return null;
  const callee = node.callee;
  if (!callee || callee.type !== "MemberExpression" || callee.computed) return null;
  if (!callee.property || callee.property.type !== "Identifier") return null;
  const method = callee.property.name;
  if (method !== "map" && method !== "filter") return null;
  const cb = callbackBody(node.arguments[0]);
  if (!cb) return null;
  return { method, src: callee.object, cb };
}

// One marker per pipeline *meaning*, shared by the loop spelling and the chain
// spelling: `xs.filter(f).map(g)` and `for (const x of xs) if (f(x)) out.push(g(x))`
// both land on PL{...}; `xs.map(g)` and `for (const x of xs) out.push(g(x))`
// both land on MAP{...}; a pipeline that maps each element to itself reduces to
// the source (or to FILTER{...} when a condition guards it), which is what makes
// `xs.filter(f)` and `for (const x of xs) { if (f(x)) out.push(x) }` agree.
function pipelineMarker(srcText, condText, elemText) {
  const bare = elemText === "Id(" + ELEM_TOK + ")";
  if (condText === null) {
    return bare ? "PL{src=" + srcText + "}" : "MAP{src=" + srcText + ",elem=" + elemText + "}";
  }
  return bare ? "FILTER{src=" + srcText + ",cond=" + condText + "}"
              : "PL{src=" + srcText + ",cond=" + condText + ",elem=" + elemText + "}";
}

function canonChainText(node, opts) {
  const outer = chainCall(node);
  if (!outer) return null;
  const elemOf = (cb) => canonExpr(cb.body, opts, { [cb.param]: ELEM_TOK });
  if (outer.method === "map") {
    // `.filter(f).map(g)` is one pipeline, not a filter applied to a map
    const inner = chainCall(outer.src);
    if (inner && inner.method === "filter" && !chainCall(inner.src)) {
      return pipelineMarker(canonExpr(inner.src, opts), elemOf(inner.cb), elemOf(outer.cb));
    }
    return pipelineMarker(canonExpr(outer.src, opts), null, elemOf(outer.cb));
  }
  // a lone filter hands the surviving elements on, i.e. element identity
  return pipelineMarker(canonExpr(outer.src, opts), elemOf(outer.cb), "Id(" + ELEM_TOK + ")");
}

// --- statement level: independence, accumulator collapse, ordering ----------

// Which names a statement reads and writes. Member property names count as
// reads too — over-reporting a dependency can only make the reorder below more
// conservative, which is the safe direction.
function readWriteNames(stmt) {
  const reads = new Set();
  const writes = new Set();
  walkAst(stmt, (n) => {
    if (n.type === "Identifier" && n.name) reads.add(n.name);
    else if (n.type === "VariableDeclarator" && n.id && n.id.type === "Identifier") writes.add(n.id.name);
    else if (n.type === "AssignmentExpression" && n.left && n.left.type === "Identifier") writes.add(n.left.name);
    else if (n.type === "UpdateExpression" && n.argument && n.argument.type === "Identifier") writes.add(n.argument.name);
  });
  return { reads, writes };
}

function sharesAny(a, b) {
  for (const name of a) if (b.has(name)) return true;
  return false;
}

function accumulatorName(stmt) {
  if (!stmt || stmt.type !== "VariableDeclaration" || stmt.declarations.length !== 1) return null;
  const d = stmt.declarations[0];
  if (!d.id || d.id.type !== "Identifier") return null;
  if (!d.init || d.init.type !== "ArrayExpression" || d.init.elements.length !== 0) return null;
  return d.id.name;
}

function pushTarget(stmt, name) {
  if (!stmt || stmt.type !== "ExpressionStatement") return null;
  const call = stmt.expression;
  if (!call || call.type !== "CallExpression" || call.arguments.length !== 1) return null;
  const callee = call.callee;
  if (!callee || callee.type !== "MemberExpression" || callee.computed) return null;
  if (!callee.object || callee.object.type !== "Identifier" || callee.object.name !== name) return null;
  if (!callee.property || callee.property.type !== "Identifier" || callee.property.name !== "push") return null;
  return call.arguments[0];
}

// `for (const v of SRC) { OUT.push(X) }` / `{ if (COND) OUT.push(X) }`
function loopAccumulatorShape(stmt, name) {
  if (!stmt || stmt.type !== "ForOfStatement") return null;
  const left = stmt.left;
  if (!left || left.type !== "VariableDeclaration" || left.declarations.length !== 1) return null;
  const d = left.declarations[0];
  if (!d.id || d.id.type !== "Identifier" || d.init) return null;
  const body = blockStatements(stmt.body);
  if (body.length !== 1) return null;
  const direct = pushTarget(body[0], name);
  if (direct) return { src: stmt.right, elem: d.id.name, cond: null, value: direct };
  if (body[0].type === "IfStatement" && !body[0].alternate) {
    const inner = blockStatements(body[0].consequent);
    if (inner.length === 1) {
      const value = pushTarget(inner[0], name);
      if (value) return { src: stmt.right, elem: d.id.name, cond: body[0].test, value };
    }
  }
  return null;
}

function referencesName(node, name) {
  let hit = false;
  walkAst(node, (n) => { if (n.type === "Identifier" && n.name === name) hit = true; });
  return hit;
}

// `const out = []; for (const x of xs) { [if (c)] out.push(f(x)) } return out;`
// computes exactly what `return xs.map(f)` / `return xs.filter(c).map(f)` /
// `return xs.filter(c)` computes, so those three statements collapse into the
// one canonical return the chain spelling already produces. Only that exact
// tail collapses, and only when nothing else touches the accumulator — a loop
// doing extra work stays a loop and keeps comparing as one.
function collapseAccumulatorTail(stmts, opts) {
  if (stmts.length < 3) return null;
  const decl = stmts[stmts.length - 3];
  const loop = stmts[stmts.length - 2];
  const ret = stmts[stmts.length - 1];
  const acc = accumulatorName(decl);
  if (!acc) return null;
  const shape = loopAccumulatorShape(loop, acc);
  if (!shape) return null;
  if (ret.type !== "ReturnStatement" || !ret.argument ||
      ret.argument.type !== "Identifier" || ret.argument.name !== acc) return null;
  for (const s of stmts.slice(0, -3)) if (readWriteNames(s).reads.has(acc)) return null;
  if (referencesName(shape.src, acc) || referencesName(shape.value, acc) ||
      (shape.cond && referencesName(shape.cond, acc))) return null;
  const seed = { [shape.elem]: ELEM_TOK };
  const marker = pipelineMarker(canonExpr(shape.src, opts),
                                shape.cond ? canonExpr(shape.cond, opts, seed) : null,
                                canonExpr(shape.value, opts, seed));
  return "ReturnStatement{argument=" + marker + "}";
}

// Statements that always transfer control stay where they are: moving a return
// past anything at all is a semantics change this pass will not paper over.
const PINNED_STATEMENTS = new Set(["ReturnStatement", "ThrowStatement", "BreakStatement", "ContinueStatement"]);

// A dependence that fixes the order of two statements: one of them writes a
// name the other reads or writes. Writes are tracked for plain identifiers
// only, so `obj.x = 1` counts as no write at all — that direction can only cost
// a missed match, never a wrong merge.
function orderedPair(a, b) {
  return sharesAny(a.writes, b.reads) || sharesAny(a.writes, b.writes) ||
         sharesAny(b.writes, a.reads);
}

// Canonical order for one run of statements: repeatedly take the smallest-key
// statement whose dependences were all emitted already. Permuting independent
// statements therefore produces the same text, while anything the author
// actually relied on stays the way the dependences fixed it.
function orderSegment(units, opts, idMap) {
  const n = units.length;
  if (n < 2) return units;
  const metas = units.map((u) => (u.text === undefined ? readWriteNames(u.node) : null));
  const done = new Array(n).fill(false);
  const keys = new Array(n).fill(null);
  const picked = [];
  for (let placed = 0; placed < n; placed++) {
    let best = -1;
    for (let i = 0; i < n; i++) {
      if (done[i]) continue;
      let ready = true;
      for (let j = 0; j < i; j++) {
        if (done[j] || !metas[j]) continue;
        if (orderedPair(metas[j], metas[i])) { ready = false; break; }
      }
      if (!ready) continue;
      // trial key: placeholders as they stand now, only frozen once emitted
      keys[i] = serializeNode(units[i].node, new Map(idMap), opts);
      if (best === -1 || keys[i] < keys[best]) best = i;
    }
    // a dependence cycle means the order was not free: keep it as written
    if (best === -1) for (let i = 0; i < n; i++) if (!done[i]) { best = i; break; }
    done[best] = true;
    picked.push(units[best]);
  }
  return picked;
}

// Pinned statements split the body into runs, so nothing is moved across a
// return, a throw or a loop control transfer.
function orderUnits(units, opts, idMap) {
  const out = [];
  let run = [];
  for (const u of units) {
    const pinned = u.text !== undefined || PINNED_STATEMENTS.has(u.node.type);
    if (!pinned) { run.push(u); continue; }
    out.push(...orderSegment(run, opts, idMap), u);
    run = [];
  }
  out.push(...orderSegment(run, opts, idMap));
  return out;
}

// The body text with both order-dependent folds applied. Serialized with the
// caller's identifier map, so the same variable used by two statements still
// resolves to the same placeholder.
function canonicalBodyText(bodyNode, opts, idMap) {
  const stmts = blockStatements(bodyNode);
  const collapsed = collapseAccumulatorTail(stmts, opts);
  const units = collapsed
    ? stmts.slice(0, -3).map((node) => ({ node })).concat([{ text: collapsed }])
    : stmts.map((node) => ({ node }));
  return orderUnits(units, opts, idMap)
    .map((u) => (u.text !== undefined ? u.text : serializeNode(u.node, idMap, opts)))
    .join(";");
}

// A function node whose body is replaced by its canonical text; everything else
// (params, name, async/generator flags) fingerprints exactly as before.
function withCanonicalBody(fnNode, opts, idMap) {
  return { ...fnNode, body: { type: "CanonicalBody", text: canonicalBodyText(fnNode.body, opts, idMap) } };
}

// ---------------------------------------------------------------------------
// near-duplicate similarity: multiset bigram Dice ratio over token arrays
// (a simple normalized-node-sequence similarity ratio -- O(n), no pairwise
//  LCS blowup; good enough for candidate generation, same "candidates not
//  verdicts" rule as the Python side)
// ---------------------------------------------------------------------------

function similarityRatio(a, b) {
  if (a.length === 0 && b.length === 0) return 1.0;
  if (a.length === 0 || b.length === 0) return 0.0;
  const bigrams = (toks) => {
    const m = new Map();
    if (toks.length === 1) { m.set(toks[0], 1); return m; }
    for (let i = 0; i < toks.length - 1; i++) {
      const g = toks[i] + " " + toks[i + 1];
      m.set(g, (m.get(g) || 0) + 1);
    }
    return m;
  };
  const ma = bigrams(a), mb = bigrams(b);
  let inter = 0;
  for (const [g, ca] of ma) {
    const cb = mb.get(g);
    if (cb) inter += Math.min(ca, cb);
  }
  return (2 * inter) / (a.length - 1 + b.length - 1);
}

// ---------------------------------------------------------------------------
// cyclomatic complexity: 1 + decision points (same formula as
// complexity_report.py's Python visitor, which uses ast.walk over the
// function node — this walks the raw AST object the same way, so nested
// functions inside a parent count toward the parent, exactly like Python)
// ---------------------------------------------------------------------------

function walkAst(node, visit) {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node)) {
    for (const item of node) walkAst(item, visit);
    return;
  }
  if (typeof node.type === "string") visit(node);
  for (const key of Object.keys(node)) {
    if (IGNORED_KEYS.has(key)) continue;
    const v = node[key];
    if (v && typeof v === "object") walkAst(v, visit);
  }
}

function complexityOf(fnNode) {
  let score = 1;
  walkAst(fnNode, (n) => {
    if (n.type === "IfStatement" || n.type === "ForStatement" || n.type === "ForInStatement" ||
        n.type === "ForOfStatement" || n.type === "WhileStatement" || n.type === "DoWhileStatement" ||
        n.type === "CatchClause" || n.type === "ConditionalExpression") {
      score += 1;
    } else if (n.type === "LogicalExpression" && ["&&", "||", "??"].includes(n.operator)) {
      score += 1;
    } else if (n.type === "SwitchCase" && n.test !== null && n.test !== undefined) {
      score += 1; // non-default case only
    }
  });
  return score;
}

// ---------------------------------------------------------------------------
// block/function collection
// ---------------------------------------------------------------------------

const FN_TYPES = new Set([
  "FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression",
  "ObjectMethod", "ClassMethod", "ClassPrivateMethod",
]);

function nonBlankLineCount(source, startLine, endLine) {
  const lines = source.split("\n");
  let n = 0;
  for (let i = startLine - 1; i < Math.min(endLine, lines.length); i++) {
    if (lines[i].trim()) n++;
  }
  return n;
}

function ownKeyName(node) {
  // Class/object methods carry their name on the node itself (their parent is
  // the ClassBody/ObjectExpression), so functionName() used to fall through to
  // "(anonymous)" — which made every method in a class report the same name.
  if (!node.key) return null;
  if (node.computed) return null;
  if (node.key.type === "Identifier") return node.key.name;
  if (node.key.type === "StringLiteral" || node.key.type === "NumericLiteral") {
    return String(node.key.value);
  }
  return null;
}

function functionName(path) {
  const node = path.node;
  if (node.id && node.id.name) return node.id.name;
  if (node.type === "ClassMethod" || node.type === "ObjectMethod" ||
      node.type === "ClassPrivateMethod") {
    if (node.kind === "constructor") return "constructor";
    const own = ownKeyName(node);
    if (own) return own;
  }
  const parent = path.parent;
  if (parent) {
    if (parent.type === "VariableDeclarator" && parent.id && parent.id.name) return parent.id.name;
    if ((parent.type === "ObjectProperty" || parent.type === "ClassProperty" ||
         parent.type === "ClassMethod" || parent.type === "ObjectMethod") &&
        parent.key && parent.key.name) return parent.key.name;
    if (parent.type === "AssignmentExpression" && parent.left.type === "Identifier") return parent.left.name;
    if (parent.type === "ExportDefaultDeclaration") return "(default)";
  }
  return "(anonymous)";
}

function qualName(path) {
  const parts = [functionName(path)];
  let p = path.parentPath;
  while (p) {
    if (FN_TYPES.has(p.node.type)) parts.unshift(functionName(p));
    else if (p.node.type === "ClassDeclaration" || p.node.type === "ClassExpression") {
      if (p.node.id) parts.unshift(p.node.id.name);
    }
    p = p.parentPath;
  }
  return parts.join(".");
}

// --mode functions (used by coverage_gap_scaffold.py to build placeholder
// calls): parameter names only, no types — TypeScript annotations would need
// TSTypeAnnotation unwrapping that the scaffold's JS stub doesn't use yet.
function paramNames(node) {
  const out = [];
  for (const p of node.params || []) {
    if (p.type === "Identifier") out.push(p.name);
    else if (p.type === "AssignmentPattern" && p.left.type === "Identifier") out.push(p.left.name);
    else if (p.type === "ObjectPattern" || p.type === "ArrayPattern") out.push("(destructured)");
    else if (p.type === "RestElement" && p.argument && p.argument.type === "Identifier") {
      out.push("..." + p.argument.name);
    } else out.push("(complex)");
  }
  return out;
}

// ---------------------------------------------------------------------------
// analysis
// ---------------------------------------------------------------------------

function analyzeFile(babel, filePath, opts) {
  const { parse, traverse } = babel;
  const source = readFileSync(filePath, "utf-8");
  let ast;
  try {
    ast = parse(source, {
      sourceType: "unambiguous",
      errorRecovery: true,
      plugins: ["typescript", "jsx", "classProperties", "decorators-legacy",
                "optionalChaining", "nullishCoalescingOperator", "dynamicImport"],
    });
  } catch (e) {
    process.stderr.write(`js_analyze.mjs: skipping unparseable file ${filePath}: ${e.message}\n`);
    return { blocks: [], functions: [] };
  }

  const blocks = [];
  const functions = [];

  traverse(ast, {
    enter(path) {
      if (!FN_TYPES.has(path.node.type)) return;
      const node = path.node;
      const line = node.loc ? node.loc.start.line : 0;
      const endLine = node.loc ? node.loc.end.line : line;

      // complexity entry (always collected when requested)
      const fnEntry = {
        file: filePath,
        function: qualName(path),
        line,
        complexity: complexityOf(node),
      };
      if (opts.mode === "functions") {
        // additive fields, present only in --mode functions so the
        // --save/--diff complexity shape stays byte-compatible with Python
        fnEntry.endLine = endLine;
        fnEntry.params = paramNames(node);
      }
      functions.push(fnEntry);

      // structural fingerprint block, subject to --min-lines (skipped
      // entirely in --mode functions — that mode only needs signatures)
      const nLines = nonBlankLineCount(source, line, endLine);
      if (opts.mode !== "functions" && nLines >= opts.minLines) {
        const idMap = new Map();
        // --canonicalize fingerprints the function with its body swapped for the
        // statement-order-canonical text; without the flag this is byte-identical
        // to what the structural pass always emitted
        const root = opts.canonicalize ? withCanonicalBody(node, opts, idMap) : node;
        const tokens = [serializeNode(root, idMap, opts)];
        // keep the token list comparable: serialize() returns one string,
        // split into subtokens for the bigram similarity ratio
        const tokenList = tokens[0].split(/(?<=\}\)|\]\)|\))|,(?=[A-Za-z])|,(?=\{)/);
        blocks.push({
          path: filePath,
          line,
          nLines,
          fingerprint: fingerprint(tokens),
          tokens: tokenList,
          name: qualName(path),
        });
      }
    },
  });
  return { blocks, functions };
}

function findDuplicates(allBlocks, opts) {
  // exact structural duplicates: same normalized fingerprint
  const byHash = new Map();
  for (const b of allBlocks) {
    if (!byHash.has(b.fingerprint)) byHash.set(b.fingerprint, []);
    byHash.get(b.fingerprint).push({ path: b.path, line: b.line });
  }
  const exactClusters = [...byHash.values()].filter((c) => c.length > 1);
  exactClusters.sort((a, b) => b.length - a.length);

  // near duplicates among unique fingerprints, capped like the Python side
  const unique = [];
  const seen = new Set();
  for (const b of allBlocks) {
    if (seen.has(b.fingerprint)) continue;
    seen.add(b.fingerprint);
    unique.push(b);
  }
  const nearPairs = [];
  let compared = 0;
  outer:
  for (let i = 0; i < unique.length; i++) {
    for (let j = i + 1; j < unique.length; j++) {
      if (compared >= opts.maxCompare) break outer;
      compared++;
      const a = unique[i], b = unique[j];
      const la = a.tokens.join(" ").length, lb = b.tokens.join(" ").length;
      if (Math.abs(la - lb) > Math.max(la, lb) * 0.4) continue; // cheap pre-filter
      const ratio = similarityRatio(a.tokens, b.tokens);
      if (ratio >= opts.similarity) {
        nearPairs.push({
          ratio: Math.round(ratio * 100) / 100,
          a: { path: a.path, line: a.line },
          b: { path: b.path, line: b.line },
        });
      }
    }
  }
  nearPairs.sort((x, y) => y.ratio - x.ratio);
  const result = { exact_clusters: exactClusters, near_pairs: nearPairs, compared };
  // The deep pass advertises itself so a caller can never mistake a
  // canonicalized hit for a structural one; the default payload is unchanged
  // (same keys, same order) so existing consumers stay byte-compatible.
  if (opts.canonicalize) result.canonicalize = true;
  return result;
}

function summarizeComplexity(results) {
  if (results.length === 0) {
    return { functions: 0, total_complexity: 0, avg_complexity: 0.0, max_complexity: 0 };
  }
  const total = results.reduce((s, r) => s + r.complexity, 0);
  return {
    functions: results.length,
    total_complexity: total,
    avg_complexity: Math.round((total / results.length) * 100) / 100,
    max_complexity: Math.max(...results.map((r) => r.complexity)),
  };
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const babel = await loadBabel();

  // Precedence: explicit CLI flag > shrinkcode.config.json > built-in default
  const config = loadConfig(resolve(opts.path));
  if (opts.minLines === null) opts.minLines = config.duplication.minLines ?? 5;
  if (opts.similarity === null) opts.similarity = config.duplication.similarity ?? 0.85;

  const rootAbs = resolve(opts.path);
  const files = iterFiles(rootAbs).filter((f) => {
    const rel = rootAbs.endsWith("\\") || rootAbs.endsWith("/")
      ? f.slice(rootAbs.length)
      : f.slice(rootAbs.length + 1);
    return !matchesExclude(rel, config.excludePaths);
  });
  if (files.length === 0) {
    // still emit valid, consumable JSON so callers don't have to special-case
    const empty = { exact_clusters: [], near_pairs: [], compared: 0 };
    if (opts.canonicalize) empty.canonicalize = true;
    const emptyC = { per_function: [], totals: summarizeComplexity([]) };
    const payload = opts.mode === "functions"
      ? { functions: [] }
      : {
          ...(opts.mode !== "complexity" ? { duplicates: empty } : {}),
          ...(opts.mode !== "duplicates" ? { complexity: emptyC } : {}),
        };
    process.stdout.write(JSON.stringify(payload, null, 2) + "\n");
    process.exit(0);
  }

  let allBlocks = [];
  let allFunctions = [];
  for (const f of files) {
    const { blocks, functions } = analyzeFile(babel, f, opts);
    allBlocks = allBlocks.concat(blocks);
    allFunctions = allFunctions.concat(functions);
  }

  const out = {};

  if (opts.mode === "functions") {
    // signature-only dump for coverage_gap_scaffold.py: {file, function,
    // line, endLine, params, complexity}
    process.stdout.write(JSON.stringify({ functions: allFunctions }, null, 2) + "\n");
    return;
  }

  if (opts.mode !== "complexity") {
    out.duplicates = findDuplicates(allBlocks, opts);
  }

  if (opts.mode !== "duplicates") {
    const totals = summarizeComplexity(allFunctions);
    const snapshot = { per_function: allFunctions, totals };

    if (opts.save) {
      writeFileSync(opts.save, JSON.stringify(snapshot, null, 2));
      process.stdout.write(`Saved complexity snapshot (${totals.functions} functions) to ${opts.save}\n`);
      return;
    }
    if (opts.diff) {
      // same table shape as complexity_report.py --diff
      const baseline = JSON.parse(readFileSync(opts.diff, "utf-8"));
      const b = baseline.totals;
      let table = "Metric              Before      After     Delta\n";
      for (const key of ["functions", "total_complexity", "avg_complexity", "max_complexity"]) {
        const before = b[key], after = totals[key];
        const delta = after - before;
        table += `${key.padEnd(19)} ${String(before).padStart(8)} ${String(after).padStart(10)} ${String(delta).padStart(8).replace(/^/, delta >= 0 ? "+" : "")}\n`;
      }
      process.stdout.write(table);
      return;
    }
    out.complexity = snapshot;
  }

  process.stdout.write(JSON.stringify(out, null, 2) + "\n");
}

main().catch((e) => {
  process.stderr.write(`js_analyze.mjs: ${e && e.stack ? e.stack : e}\n`);
  process.exit(1);
});





