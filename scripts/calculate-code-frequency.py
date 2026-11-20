#!/usr/bin/env python3

from pathlib import Path
from urllib.request import Request, urlopen
import json
import os
import subprocess
import sys
import tempfile

USERNAME = os.environ.get("GH_USERNAME", "rootagi")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "neofetch.json"))

EXCLUDED_REPOS = {
    name.strip().lower()
    for name in os.environ.get("EXCLUDE_REPOS", "walls,wallpaper").split(",")
    if name.strip()
}

INCLUDE_FORKS = os.environ.get("INCLUDE_FORKS", "false").lower() == "true"


def get_public_repositories():
    repositories = []
    page = 1

    while True:
        url = (
            f"https://api.github.com/users/{USERNAME}"
            f"/repos?type=public&per_page=100&page={page}"
        )

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "code-frequency-calculator",
        }

        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"

        request = Request(url, headers=headers)

        with urlopen(request, timeout=30) as response:
            batch = json.loads(response.read().decode("utf-8"))

        if not batch:
            break

        for repo in batch:
            if repo["name"].lower() in EXCLUDED_REPOS:
                print(f"Skipping excluded repository: {repo['name']}")
                continue

            if repo.get("private"):
                continue

            if repo.get("fork") and not INCLUDE_FORKS:
                continue

            repositories.append(repo)

        if len(batch) < 100:
            break

        page += 1

    return repositories


def calculate_repository_frequency(repo, totals):
    repo_name = repo["full_name"]
    repo_url = repo["clone_url"]
    if TOKEN:
        repo_url = repo_url.replace("https://", f"https://x-access-token:{TOKEN}@")

    print(f"\nProcessing: {repo_name}")

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_path = str(Path(tmpdir) / "repository.git")

        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--bare",
                    "--quiet",
                    repo_url,
                    clone_path,
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            print(f"  Warning: failed to clone {repo_name}: {exc}")
            return

        cmd = [
            "git",
            "-C",
            clone_path,
            "log",
            "--no-merges",
            "--numstat",
            "--format=",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            print(f"  Warning: failed to get git log for {repo_name}: {exc}")
            return

    repo_additions = 0
    repo_deletions = 0

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) != 3:
            continue

        additions, deletions, _ = parts

        # Binary files contain "-" instead of line counts.
        if additions.isdigit() and deletions.isdigit():
            repo_additions += int(additions)
            repo_deletions += int(deletions)

    print(f"  + {repo_additions:,} / - {repo_deletions:,}")
    totals["additions"] += repo_additions
    totals["deletions"] += repo_deletions


def update_neofetch_config(total_additions, total_deletions):
    if not CONFIG_PATH.exists():
        print(f"Warning: {CONFIG_PATH} not found — skipping config patch")
        return

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)

    if "stats" not in config:
        config["stats"] = {}

    rows = config.get("stats", {}).get("rows", [])
    new_rows = []
    patched = False

    new_row = {
        "left": {
            "key": "+++",
            "value": f"{total_additions:,}",
            "keyColor": "#188038, #81c995",
            "valueColor": "#188038, #81c995",
        },
        "right": {
            "key": "---",
            "value": f"{total_deletions:,}",
            "keyColor": "#d93025, #f28b82",
            "valueColor": "#d93025, #f28b82",
        },
    }

    for row in rows:
        if row == "loc":
            continue  # drop service's fake estimate if present
        if isinstance(row, dict):
            left_key = str(row.get("left", {}).get("key", ""))
            right_key = str(row.get("right", {}).get("key", ""))
            if left_key in ("Lines of Code", "+", "+++") or right_key in ("Tool", "-", "---"):
                new_rows.append(new_row)
                patched = True
                continue
        new_rows.append(row)

    if not patched:
        new_rows.append(new_row)

    config["stats"]["rows"] = new_rows

    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"\nUpdated {CONFIG_PATH} successfully:")
    print(f"  + : {total_additions:,}")
    print(f"  - : {total_deletions:,}")


def main():
    print(f"Fetching public repositories for {USERNAME}...")
    repositories = get_public_repositories()
    print(f"Found {len(repositories)} repositories.")

    totals = {"additions": 0, "deletions": 0}

    for index, repo in enumerate(repositories, start=1):
        print(f"[{index}/{len(repositories)}]", end=" ")
        calculate_repository_frequency(repo, totals)

    total_additions = totals["additions"]
    total_deletions = totals["deletions"]

    print("\nCode frequency calculation complete.")
    print(f"Repositories processed: {len(repositories)}")
    print(f"Total additions: {total_additions:,}")
    print(f"Total deletions: {total_deletions:,}")
    print(f"Net change: {total_additions - total_deletions:,}")

    update_neofetch_config(total_additions, total_deletions)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
