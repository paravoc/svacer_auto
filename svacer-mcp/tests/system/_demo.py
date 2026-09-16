"""Pinned references to data on svacer-demo.ispras.ru.

Values here are filled by running `python -m tests.system._discover` against the
stand. If the stand changes (project renamed, snapshots rotated), rerun discover
and paste new values here.
"""

# Project picked as our stable reference on the demo stand.
PROJECT_NAME = "openssl"
PROJECT_ID = "d6ba3326-057d-4f57-9532-7ecda38c91d0"

# A branch of the above project with a non-empty snapshot history.
BRANCH_NAME = "master"
BRANCH_ID = "a2447f35-8bf2-4b5d-bf9c-c6dd3441df3b"

# Two most recent snapshots on that branch — newest first.
# get_diff uses both; everything else uses SNAPSHOT_ID.
SNAPSHOT_ID = "82106a74-a09b-4795-87ab-747f5fc5a0da"
SNAPSHOT_PREV_ID = "5adcf4ec-603d-48b5-ae08-a87f5a382278"

# A file referenced by at least one warning in SNAPSHOT_ID.
FILE_PATH = ".build/providers/implementations/kdfs/scrypt.c"
