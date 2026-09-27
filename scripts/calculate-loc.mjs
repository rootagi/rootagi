#!/usr/bin/env node
/**
 * calculate-loc.mjs
 *
 * Lists every public, non-fork repo for GH_USERNAME, shallow-clones each
 * one, runs `cloc` against it, and sums the real "code" line counts
 * (blank + comment lines excluded, matching cloc's own headline number).
 *
 * Then patches the "Lines of Code" row in neofetch.json with the result,
 * and writes loc.json as a small cache/audit trail.
 *
 * Requires: Node 18+ (global fetch), `cloc` on PATH, `git` on PATH.
 */

import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const USERNAME = process.env.GH_USERNAME;
const TOKEN = process.env.GITHUB_TOKEN;
const CONFIG_PATH = process.env.CONFIG_PATH || "neofetch.json";
const INCLUDE_FORKS = process.env.INCLUDE_FORKS === "true";
// Directories to skip inside every clone, so vendored/generated code
// doesn't inflate the count the way it doesn't when you run cloc yourself.
const EXCLUDE_DIRS = (
  process.env.EXCLUDE_DIRS ||
  "node_modules,vendor,dist,build,.git,target,venv,.venv"
).trim();
// Whole repos to skip entirely, by name (e.g. media/wallpaper dumps that
// are gigabytes in size and contain no source code). --depth 1 still
// pulls the full blob contents of the latest commit, so shallow-cloning
// alone won't save you here — these need to be skipped before cloning.
const EXCLUDE_REPOS = (process.env.EXCLUDE_REPOS || "")
  .split(",")
  .map((s) => s.trim().toLowerCase())
  .filter(Boolean);
// Belt-and-suspenders: also skip anything over this size (GitHub's
// reported repo size, in KB) even if it wasn't named above, so a future
// large repo doesn't silently blow up a run. Set to 0 to disable.
const MAX_REPO_SIZE_KB = Number(process.env.MAX_REPO_SIZE_KB || 500000); // ~500MB

if (!USERNAME) {
  console.error("GH_USERNAME env var is required");
  process.exit(1);
}

const headers = {
  Accept: "application/vnd.github+json",
  ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
};

async function listPublicRepos(username) {
  const repos = [];
  let page = 1;
  for (;;) {
    const res = await fetch(
      `https://api.github.com/users/${username}/repos?type=public&per_page=100&page=${page}`,
      { headers }
    );
    if (!res.ok) {
      throw new Error(`GitHub API error ${res.status}: ${await res.text()}`);
    }
    const batch = await res.json();
    if (batch.length === 0) break;
    repos.push(...batch);
    if (batch.length < 100) break;
    page += 1;
  }
  return repos.filter((r) => {
    if (!INCLUDE_FORKS && r.fork) return false;
    if (r.archived) return false;
    if (EXCLUDE_REPOS.includes(r.name.toLowerCase())) {
      console.log(`Skipping ${r.full_name} (explicitly excluded)`);
      return false;
    }
    if (MAX_REPO_SIZE_KB > 0 && r.size > MAX_REPO_SIZE_KB) {
      console.log(
        `Skipping ${r.full_name} (size ${r.size} KB exceeds ${MAX_REPO_SIZE_KB} KB cap)`
      );
      return false;
    }
    return true;
  });
}

function cloneAndCount(repo, workDir) {
  const dest = path.join(workDir, repo.name);
  const cloneUrl = TOKEN
    ? repo.clone_url.replace("https://", `https://x-access-token:${TOKEN}@`)
    : repo.clone_url;

  console.log(`Cloning ${repo.full_name}...`);
  try {
    execSync(`git clone --depth 1 --quiet "${cloneUrl}" "${dest}"`, {
      stdio: "ignore",
    });
  } catch {
    console.warn(`  skipped (clone failed): ${repo.full_name}`);
    return 0;
  }

  try {
    const clocJson = execSync(
      `cloc --json --quiet --exclude-dir=${EXCLUDE_DIRS} "${dest}"`,
      { maxBuffer: 1024 * 1024 * 50 }
    ).toString();
    const parsed = JSON.parse(clocJson);
    const code = parsed.SUM ? parsed.SUM.code : 0;
    console.log(`  ${repo.full_name}: ${code} lines`);
    return code;
  } catch {
    console.warn(`  skipped (cloc failed, likely no source files): ${repo.full_name}`);
    return 0;
  } finally {
    fs.rmSync(dest, { recursive: true, force: true });
  }
}

async function main() {
  const repos = await listPublicRepos(USERNAME);
  console.log(`Found ${repos.length} public repos for ${USERNAME}`);

  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "loc-"));
  let total = 0;

  for (const repo of repos) {
    total += cloneAndCount(repo, workDir);
  }
  fs.rmSync(workDir, { recursive: true, force: true });

  console.log(`\nTotal lines of code across ${repos.length} public repos: ${total}`);

  const formatted = total.toLocaleString("en-US");

  if (fs.existsSync(CONFIG_PATH)) {
    const config = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
    const rows = config.stats?.rows || [];
    let patched = false;

    for (const row of rows) {
      if (row?.left?.key === "Lines of Code") {
        row.left.value = formatted;
        patched = true;
      }
    }

    if (!patched) {
      rows.push({
        left: { key: "Lines of Code", value: formatted },
        right: { key: "Tool", value: "cloc" },
      });
    }

    fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2) + "\n");
    console.log(`Updated ${CONFIG_PATH}`);
  } else {
    console.warn(`${CONFIG_PATH} not found — skipping config patch`);
  }

  fs.writeFileSync(
    "loc.json",
    JSON.stringify(
      { total, repos: repos.length, updatedAt: new Date().toISOString() },
      null,
      2
    ) + "\n"
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
