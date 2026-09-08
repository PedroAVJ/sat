import assert from "node:assert/strict";
import { mkdtemp, readFile, realpath, stat, symlink } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("Codex and Claude manifests stay synchronized", async () => {
  const codex = JSON.parse(await readFile(path.join(root, ".codex-plugin/plugin.json"), "utf8"));
  const claude = JSON.parse(await readFile(path.join(root, ".claude-plugin/plugin.json"), "utf8"));
  for (const key of ["name", "version", "description", "author", "homepage", "repository", "license", "keywords", "skills"]) {
    assert.deepEqual(codex[key], claude[key]);
  }
});

test("plugin package contains behavior but no private record directories", async () => {
  const ignore = await readFile(path.join(root, ".gitignore"), "utf8");
  for (const entry of ["private/", "records/", "credentials/", "secrets/"]) {
    assert.match(ignore, new RegExp(`^${entry.replace("/", "\\/")}$`, "m"));
  }
  await stat(path.join(root, "scripts/sat_cli.py"));
  await stat(path.join(root, "skills/sat/SKILL.md"));
});

test("original tax-record icon backs both plugin surfaces", async () => {
  const manifest = JSON.parse(await readFile(path.join(root, ".codex-plugin/plugin.json"), "utf8"));
  assert.equal(manifest.interface.category, "Finance");
  assert.equal(manifest.interface.brandColor, "#0055B8");
  assert.equal(manifest.interface.composerIcon, "./assets/sat-icon.svg");
  assert.equal(manifest.interface.logo, "./assets/sat-icon.svg");
  const iconPath = path.join(root, "assets/sat-icon.svg");
  const icon = await stat(iconPath);
  assert.ok(icon.size > 0);
  assert.match(await readFile(iconPath, "utf8"), /<svg[^>]+xmlns="http:\/\/www\.w3\.org\/2000\/svg"/);
  await stat(path.join(root, "ICON-SOURCES.md"));
});

test("stable CLI shim resolves the installed plugin instead of the symlink directory", async () => {
  const temporary = await mkdtemp(path.join(tmpdir(), "sat-shim-"));
  const shim = path.join(temporary, "sat");
  await symlink(path.join(root, "bin/sat"), shim);
  const output = execFileSync(shim, ["--json", "store", "path"], {
    encoding: "utf8",
    env: { ...process.env, SAT_STORE_ROOT: path.join(temporary, "store") },
  });
  const payload = JSON.parse(output);
  assert.equal(payload.ok, true);
  assert.equal(payload.store_root, await realpath(temporary) + "/store");
});
