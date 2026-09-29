// Acceptance test for prompt #3's comment-update logic: simulate two pushes
// to the same PR and prove only ONE shrinkcode comment exists, updated in
// place. Runs the REAL module the workflow loads (.github/shrinkcode-comment-sync.js).
//
//   node test_comment_sync.js <path-to-shrinkcode-comment-sync.js>
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("usage: node test_comment_sync.js <path-to-shrinkcode-comment-sync.js>");
  process.exit(2);
}
const sync = require(path.resolve(modulePath));
const MARKER = "<!-- shrinkcode-bot -->";

function makeFake() {
  const state = { comments: [], created: 0, updated: [], deleted: [] };
  const github = {
    rest: {
      issues: {
        async listComments() {
          return { data: state.comments.map((c) => ({ ...c })) };
        },
        async createComment({ body }) {
          state.created += 1;
          const c = { id: 1000 + state.comments.length, body };
          state.comments.push(c);
          return { data: c };
        },
        async updateComment({ comment_id, body }) {
          state.updated.push(comment_id);
          const c = state.comments.find((x) => x.id === comment_id);
          assert(c, "update must target an existing comment");
          c.body = body;
          return { data: c };
        },
        async deleteComment({ comment_id }) {
          state.deleted.push(comment_id);
          state.comments = state.comments.filter((x) => x.id !== comment_id);
        },
      },
    },
  };
  const context = { repo: { owner: "octo", repo: "demo" }, issue: { number: 7 } };
  const logs = [];
  const core = {
    info: (m) => logs.push(`info: ${m}`),
    warning: (m) => logs.push(`warning: ${m}`),
  };
  return { github, context, core, state, logs };
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "shrinkcode-sync-"));
const body1 = path.join(tmp, "push1.md");
const body2 = path.join(tmp, "push2.md");
const noMarker = path.join(tmp, "nomarker.md");
const missing = path.join(tmp, "does-not-exist.md");
fs.writeFileSync(body1, `${MARKER}\n\nreport for push 1\n`, "utf8");
fs.writeFileSync(body2, `${MARKER}\n\nreport for push 2\n`, "utf8");
fs.writeFileSync(noMarker, "oops, no marker here\n", "utf8");

(async () => {
  // --- push 1: no comments yet -> create exactly one ---
  const f1 = makeFake();
  const r1 = await sync({ ...f1, bodyPath: body1 });
  assert.strictEqual(r1.action, "created", "first push creates");
  assert.strictEqual(f1.state.created, 1, "one create call on push 1");
  assert.strictEqual(f1.state.comments.length, 1, "one comment after push 1");
  assert.ok(f1.state.comments[0].body.includes(MARKER), "comment carries marker");

  // --- push 2: same PR, updated body -> update in place, no second comment ---
  const r2 = await sync({ ...f1, bodyPath: body2 });
  assert.strictEqual(r2.action, "updated", "second push updates");
  assert.strictEqual(f1.state.created, 1, "push 2 must NOT create a comment");
  assert.strictEqual(f1.state.comments.length, 1, "still exactly one comment");
  assert.ok(f1.state.comments[0].body.includes("push 2"), "body replaced in place");
  assert.deepStrictEqual(f1.state.updated, [f1.state.comments[0].id],
    "update targeted the existing comment id");

  // --- duplicate marked comments (historical race) -> collapses back to one ---
  const f2 = makeFake();
  await sync({ ...f2, bodyPath: body1 });
  f2.state.comments.push({ id: 999, body: `${MARKER}\n\nstale duplicate` });
  await sync({ ...f2, bodyPath: body2 });
  assert.strictEqual(f2.state.comments.length, 1, "duplicates cleaned up");
  assert.deepStrictEqual(f2.state.deleted, [999], "stale duplicate removed");

  // --- safety rails: no marker -> refuse; missing body -> no-op ---
  const f3 = makeFake();
  const r3 = await sync({ ...f3, bodyPath: noMarker });
  assert.strictEqual(r3.action, "none", "body without marker is not posted");
  assert.strictEqual(f3.state.created, 0, "nothing posted without marker");
  const r4 = await sync({ ...f3, bodyPath: missing });
  assert.strictEqual(r4.action, "none", "missing body is a no-op, not a crash");

  console.log("comment-sync simulation: all assertions passed "
    + "(create on push 1, in-place update on push 2, single comment invariant)");
  process.exit(0);
})().catch((err) => {
  console.error("FAIL:", err.message);
  process.exit(1);
});
