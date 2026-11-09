import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { globFiles } from "@sentry/bundler-plugins/core";

// Resolve the actual chain Sentry uses, even if npm nests these packages later.
const require = createRequire(import.meta.url);
const sentryRequire = createRequire(require.resolve("@sentry/bundler-plugins/core"));
const globRequire = createRequire(sentryRequire.resolve("glob"));
const { Minimatch } = globRequire("minimatch");

async function withArtifacts(run) {
  const root = await mkdtemp(path.join(tmpdir(), "sentry-glob-test-"));
  try {
    await mkdir(path.join(root, "chunks"));
    await mkdir(path.join(root, "directory.js"));
    for (const file of ["app.js", "app.js.map", "chunks/lazy.js", "chunks/lazy.js.map", "README.txt"]) {
      await writeFile(path.join(root, file), "fixture\n");
    }
    await run(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

test("Sentry resolves patched glob and minimatch versions", () => {
  assert.equal(sentryRequire("glob/package.json").version, "14.0.4");
  assert.equal(globRequire("minimatch/package.json").version, "11.0.5");
});

test("Sentry discovers source maps with absolute paths and no directories", async () => {
  await withArtifacts(async (root) => {
    const files = await globFiles("**/*.{js,map}", { cwd: root });
    assert.deepEqual(files.sort(), ["app.js", "app.js.map", "chunks/lazy.js", "chunks/lazy.js.map"]
      .map((file) => path.join(root, file)).sort());
  });
});

test("Sentry supports pattern arrays, ignores, and unmatched assets", async () => {
  await withArtifacts(async (root) => {
    const files = await globFiles([path.join(root, "**/*.js"), path.join(root, "**/*.map")], {
      ignore: [path.join(root, "chunks/**")],
    });
    assert.deepEqual(files.sort(), [path.join(root, "app.js"), path.join(root, "app.js.map")]);
    assert.deepEqual(await globFiles("**/*.missing", { cwd: root }), []);
  });
});

test("Sentry glob traversal rejects an already cancelled signal", async () => {
  await withArtifacts(async (root) => {
    const reason = new Error("Build asset scan cancelled");
    await assert.rejects(globFiles("**/*", { cwd: root, signal: AbortSignal.abort(reason) }),
      (error) => error === reason);
  });
});

test("minimatch limits globparts amplification before allocating more rows", () => {
  assert.throws(() => new Minimatch("**/../a/b/".repeat(8) + "file.js", {
    optimizationLevel: 2,
    braceExpandMax: 16,
  }), /too many patterns/);
});
