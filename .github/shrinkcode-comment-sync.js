// Find-and-update logic for the single shrinkcode PR comment
// (v2, prompt #3). Extracted from the workflow so the exact code the workflow
// runs can be tested locally: the workflow invokes it through
// actions/github-script, which provides {github, context, core}.
const fs = require("fs");

// Hidden HTML marker: ci_diff_report.py puts it on the first line of every
// report body, and we find our comment by it instead of matching titles.
const MARKER = "<!-- shrinkcode-bot -->";

module.exports = async function sync({ github, context, core, bodyPath }) {
  if (!fs.existsSync(bodyPath)) {
    core.info(`shrinkcode: no report body at ${bodyPath} — nothing to comment`);
    return { action: "none" };
  }
  const body = fs.readFileSync(bodyPath, "utf8");
  if (!body.includes(MARKER)) {
    core.warning("shrinkcode: report body lacks the hidden marker — refusing "
      + "to post a comment we could not find again on the next push");
    return { action: "none" };
  }

  const { owner, repo } = context.repo;
  const issue_number = context.issue.number;
  const { data: comments } = await github.rest.issues.listComments({
    owner, repo, issue_number, per_page: 100,
  });
  const marked = comments.filter((c) => c.body && c.body.includes(MARKER));

  if (marked.length > 0) {
    // Update the first marked comment in place...
    const target = marked[0];
    await github.rest.issues.updateComment({
      owner, repo, comment_id: target.id, body,
    });
    // ...and clear out any duplicates an earlier race left behind, so the
    // invariant really is "one shrinkcode comment per PR".
    for (const extra of marked.slice(1)) {
      core.warning(`shrinkcode: removing duplicate marked comment ${extra.id}`);
      await github.rest.issues.deleteComment({ owner, repo, comment_id: extra.id });
    }
    core.info(`shrinkcode: updated existing comment ${target.id}`);
    return { action: "updated", comment_id: target.id };
  }

  await github.rest.issues.createComment({ owner, repo, issue_number, body });
  core.info("shrinkcode: created comment");
  return { action: "created" };
};
