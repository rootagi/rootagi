
#!/usr/bin/env python3

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import json
import os
import subprocess
import sys
import tempfile


USERNAME = os.environ.get("GH_USERNAME", "rootagi")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

EXCLUDED_REPOS = {
    name.strip()
    for name in os.environ.get(
        "EXCLUDE_REPOS", ""
    ).split(",")
    if name.strip()
}

INCLUDE_FORKS = (
    os.environ.get("INCLUDE_FORKS", "false").lower()
    == "true"
)

OUTPUT_FILE = Path("code-frequency.json")


def get_sunday_timestamp(unix_ts):
    dt = datetime.fromtimestamp(
        unix_ts,
        tz=timezone.utc
    )

    days_since_sunday = (dt.weekday() + 1) % 7

    sunday = dt.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    ) - timedelta(days=days_since_sunday)

    return int(sunday.timestamp())


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
            if repo["name"] in EXCLUDED_REPOS:
                print(f"Skipping excluded repository: {repo['name']}")
                continue

            if repo["private"]:
                continue

            if repo["fork"] and not INCLUDE_FORKS:
                continue

            repositories.append(repo)

        if len(batch) < 100:
            break

        page += 1

    return repositories


def calculate_repository_frequency(repo, weekly_stats):
    repo_name = repo["full_name"]
    repo_url = repo["clone_url"]

    print(f"\nProcessing: {repo_name}")

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_path = str(Path(tmpdir) / "repository.git")

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
        )

        cmd = [
            "git",
            "-C",
            clone_path,
            "log",
            "--no-merges",
            "--numstat",
            "--format=COMMIT:%ct",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

    current_week = None

    for line in result.stdout.splitlines():

        if line.startswith("COMMIT:"):
            timestamp = int(line.split(":")[1])
            current_week = get_sunday_timestamp(timestamp)

        elif line.strip() and current_week is not None:
            parts = line.split("\t")

            if len(parts) != 3:
                continue

            additions, deletions, _ = parts

            # Binary files contain "-" instead of line counts.
            if additions.isdigit() and deletions.isdigit():
                weekly_stats[current_week]["additions"] += int(additions)
                weekly_stats[current_week]["deletions"] += int(deletions)


def main():
    print(f"Fetching public repositories for {USERNAME}...")

    repositories = get_public_repositories()

    print(f"Found {len(repositories)} repositories.")

    weekly_stats = defaultdict(
        lambda: {
            "additions": 0,
            "deletions": 0,
        }
    )

    for index, repo in enumerate(repositories, start=1):
        print(f"\n[{index}/{len(repositories)}]")

        calculate_repository_frequency(
            repo,
            weekly_stats,
        )

    output = [
        [
            week,
            stats["additions"],
            -stats["deletions"],
        ]
        for week, stats in sorted(weekly_stats.items())
    ]

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(output, file, indent=2)

    total_additions = sum(
        item[1] for item in output
    )

    total_deletions = sum(
        -item[2] for item in output
    )

    print("\nCode frequency calculation complete.")
    print(f"Repositories processed: {len(repositories)}")
    print(f"Weeks recorded: {len(output)}")
    print(f"Total additions: {total_additions:,}")
    print(f"Total deletions: {total_deletions:,}")
    print(f"Net change: {total_additions - total_deletions:,}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    try:
        main()

    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
