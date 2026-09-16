"""One-shot script to print pinned references from a live Svacer stand.

Run when setting up system tests for the first time, or when the stand changes
and the constants in tests/system/_demo.py go stale.

    .venv/bin/python -m tests.system._discover

Reads credentials via SvacerConfig (env vars or .env). Copy the printed
constants into tests/system/_demo.py.
"""
import asyncio

from svacer_mcp.api_client import SvacerAPIClient
from svacer_mcp.auth import SvacerAuth
from svacer_mcp.config import SvacerConfig
from svacer_mcp.utils.filters import FilterBuilder


async def _run():
    cfg = SvacerConfig()
    print(f"# stand: {cfg.url} (login: {cfg.login})\n")

    auth = SvacerAuth(cfg.url, cfg.login, cfg.password, cfg.timeout)
    async with SvacerAPIClient(auth) as client:
        await auth.authenticate()

        projects = await client.get_projects()
        if not projects:
            print("# no projects on stand — nothing to pin")
            return

        print(f"# {len(projects)} projects on stand:")
        for item in projects:
            project = item["project"]
            print(f"#   - {project['name']!r} id={project['id']} branches={len(item['branches'])}")
        print()

        # Walk projects, pick the first one with the most snapshots on any branch.
        best = None  # (project, branch, snapshots_list)
        for item in projects:
            project = item["project"]
            for branch in item["branches"]:
                filter_b64 = FilterBuilder().build_snapshots_filter(project["id"], branch["id"])
                raw = await client.get_snapshots_flat(filter_b64)
                flat = [s for g in raw for s in g.get("snapshots", [])]
                print(f"#   {project['name']!r}/{branch['name']!r}: {len(flat)} snapshots")
                if best is None or len(flat) > len(best[2]):
                    best = (project, branch, flat)

        if not best or not best[2]:
            print("# no snapshots found on any project — cannot pin anything")
            return

        project, branch, snapshots = best
        newest = snapshots[0]
        prev = snapshots[1] if len(snapshots) >= 2 else None

        # First file referenced by any warning in the newest snapshot.
        warnings = await client.get_warnings(project["id"], branch["id"], newest["id"])
        file_path = next((w.get("file") for w in warnings if w.get("file")), "")

        print()
        print("# paste into tests/system/_demo.py")
        print(f'PROJECT_NAME = {project["name"]!r}')
        print(f'PROJECT_ID = {project["id"]!r}')
        print(f'BRANCH_NAME = {branch["name"]!r}')
        print(f'BRANCH_ID = {branch["id"]!r}')
        print(f'SNAPSHOT_ID = {newest["id"]!r}             # {newest.get("name", "")}')
        if prev:
            print(f'SNAPSHOT_PREV_ID = {prev["id"]!r}        # {prev.get("name", "")}')
        else:
            print('SNAPSHOT_PREV_ID = ""                    # no second snapshot — get_diff will fail')
        print(f'FILE_PATH = {file_path!r}')


if __name__ == "__main__":
    asyncio.run(_run())
