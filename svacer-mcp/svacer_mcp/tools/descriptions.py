# === Server-level instructions ===

SERVER_INSTRUCTIONS = (
    "Svacer is a platform for aggregating, reviewing and analyzing results of static code analysis. "
    "It supports importing results in SARIF and native formats. "
    "Native format can be used only for results of Svace static analyser. "
    "Data is organized as: Project → Branch → Snapshot → Markers (also known as warnings, issues, defects, problems). "
    "Project is a container for branches. Branch is a container for snapshots. "
    "Snapshot contains list of markers. Marker defines some issue found by a static code analyzer in source code. "
    "Recommended call order: get_projects → get_snapshots → analysis tools "
    "(get_markers, get_warnings, get_project_stats, get_diff, get_advanced_file_preview). "
    "Project groups are a separate concept — use get_project_groups to look them up. "
    "Markup upload is a separate two-step operation: prepare_markup_import is read-only, "
    "then apply_markup_import changes Svacer only with the exact human confirmation phrase."
)

# === Common parameter descriptions (shared across multiple tools) ===

PARAM_PROJECT_ID = "UUID of the project (from get_projects)"
PARAM_BRANCH_ID = "UUID of the branch (from get_projects)"
PARAM_SNAPSHOT_ID = "UUID of the snapshot (from get_snapshots)"

PARAM_REVIEW = (
    "Filter by review status (API field: review.status). "
    "Valid values: \"Confirmed\", \"Won't fix\", \"False Positive\", \"Unclear\". "
    "Markers without a review record are excluded when this filter is set."
)

PARAM_WARN_CLASS = (
    "Filter by checker identifier (API field: warnClass). "
    "Examples: \"DEREF_AFTER_NULL\", \"INVARIANT_RESULT\". "
    "This is the checker identifier, not the tool/analyzer name."
)

PARAM_FILE = (
    "Filter by file path substring (API field: file). "
    "Example: \"/.build/execute_cmd.c\"."
)

PARAM_CHECKER_INFO = (
    "Include checker metadata (checkerInfo field with description, CWE, etc.) in each marker."
)

PARAM_REVIEW_HISTORY = (
    "Include full history of review status changes (review_history field) in each warning."
)

PARAM_COMMENT_HISTORY = (
    "Include all comments left on the marker (comments field) in each warning."
)

PARAM_CUSTOM_FILTER = (
    "Apply a saved custom filter by its ID or name. Custom filters are created in the Svacer UI."
)

PARAM_ADVANCED_FILTER = (
    "Apply a Svacer advanced-filter expression and keep only the returned marker IDs. "
    "Example: filter(markers, \"ГОСТ 71207-2024\" in .checker_labels). "
    "Use this when a saved custom-filter name is not accepted by the server API."
)

PARAM_LIMIT = (
    "Maximum number of markers to return (default 30). Keeps responses compact for LLM context. "
    "If the response is truncated, the result includes total_count and truncated:true — narrow "
    "filters (severity/warnClass/file) or raise this limit explicitly. Pass 0 to disable the cap."
)

PARAM_LIMIT_WARNINGS = (
    "Maximum number of warnings to return (default 30, or 8 when traces/review_history/"
    "comment_history are enabled — each such warning is much larger). Keeps responses compact "
    "for LLM context. If the response is truncated, total_count plus truncated:true appear in "
    "the result — narrow filters or raise this limit explicitly. Pass 0 to disable the cap."
)

PARAM_FIELDS = (
    "Optional whitelist of top-level marker fields to return. "
    "Default is a compact preset (id, warnClass, file, line, msg, function, review). "
    "Pass [\"*\"] to get every field, or an explicit list like [\"id\",\"warnClass\"] to narrow further. "
    "Use this to keep responses small when only a few fields are needed."
)

# === Severity: two variants (client-side vs server-side filtering) ===

_SEVERITY_BASE = (
    "Filter by review severity (API field: review.severity). "
    "Valid values: \"Critical\", \"Major\", \"Minor\", \"Unspecified\". "
    "Only markers that have a review record can have a severity."
)

PARAM_SEVERITY_WARNINGS = _SEVERITY_BASE + " Applied client-side for this endpoint."
PARAM_SEVERITY_MARKERS = _SEVERITY_BASE + " Applied client-side for this endpoint."

# === Traces: two variants (wording differs between markers and warnings) ===

PARAM_TRACES_WARNINGS = (
    "Include call traces (chain of calls leading to the defect) in each warning."
)

PARAM_TRACES_MARKERS = (
    "Include marker traces (list of source locations describing the defect) in each marker."
)

# === diff.py-specific parameters ===

PARAM_BASE_SNAPSHOT_ID = (
    "UUID of the base (older) snapshot. Use get_snapshots to find it."
)

PARAM_HEAD_SNAPSHOT_ID = (
    "UUID of the head (newer) snapshot. "
    "If omitted, compares against the previous snapshot automatically."
)

PARAM_DIFF_LEVEL = (
    "Detail level: 0=statistics only (default), 1=statistics+marker IDs, 2=full marker details"
)

PARAM_DIFF_LIMIT = (
    "Maximum number of markers to return per category (new_markers/missing_markers/"
    "modified_markers/matched_markers) when level>=2. Each category is capped independently; "
    "total_count and truncated:true appear inside each category if it was cut. "
    "Pass 0 to disable the cap. Ignored when level<2."
)

# === file_preview.py-specific parameters ===

PARAM_PREVIEW_SNAPSHOT_ID = (
    "UUID of the snapshot (from get_snapshots or from a marker's snapshot field)"
)

PARAM_FILE_PATH = "Path to the file as returned by markers (e.g. src/main.c)"

PARAM_LINE = "Center line number (1-indexed)"

PARAM_BEFORE = "Number of lines to include before the center line"

PARAM_AFTER = (
    "Number of lines to include after the center line. Set to 99999 to get the entire file."
)

# === snapshots.py-specific parameters ===

PARAM_NAME_FILTER = "Filter snapshots by name (substring or regex pattern)"

# === project_groups.py-specific parameters ===

PARAM_NAME_OR_ID = "Name or UUID of the project group to retrieve"

# === Tool function descriptions ===

GET_PROJECTS = """\
List all projects in Svacer with their branches.

START HERE — call first to get project_id and branch_id needed by other tools.
Returns project_id (UUID) and branch_id (UUID) for each project and branch.
After getting these, use get_snapshots to obtain snapshot_id.\
"""

GET_SNAPSHOTS = """\
List snapshots for a project branch.

Use after get_projects to get snapshot_id (UUID) needed by get_markers,
get_warnings, get_diff, and get_advanced_file_preview.
Returns snapshot_id, name, import_time, commit_hash, and markers_count for each
snapshot. commit_hash is pulled from details.custom_properties (looking for any
field whose name contains "commit") and may be null when the project doesn't
record one. markers_count is fetched from get_markers per snapshot — heavier
than a plain listing, but reliable (snapshot details aren't always populated).\
"""

GET_WARNINGS = """\
Get detailed warnings (fullmarkers) for a specific snapshot.

Default output fields: id, warnClass, file, line, msg, function, review
(object with status/severity/action). Pass fields=["*"] for the full warning
including tool/mtid; pass an explicit list like fields=["id","msg"] to narrow.
HEAVY operation — can be slow for large snapshots. Prefer get_markers for listing.
Response is capped by limit (default ~30, drops to ~8 when traces/review_history/
comment_history are enabled — each warning is then much larger). If truncated:true,
narrow filters or raise limit explicitly. total_count shows the pre-truncation total.
Requires project_id, branch_id, snapshot_id — use get_projects then get_snapshots.\
"""

GET_MARKERS = """\
Get markers (also known as warnings, issues, defects, problems) with filtering.

LIGHTWEIGHT alternative to get_warnings — use for listing and overviews.
Supports filtering by severity, warnClass (also known as detector name), file, and review status.
Output fields by default: id, warnClass, file, line, msg, function, review
(object with status/severity/action). Pass fields=["*"] for the full marker including
tool/mtid; pass an explicit list like fields=["id","warnClass"] to narrow further.
Field semantics:
  id - unique marker ID (UUID)
  invariant - stable Svacer markup key (available when returned by the server)
  warnClass - detector name
  file - path (relative or absolute) to source code file
  line - line in source code file
  msg - human-readable message describing the defect identified by this marker
  function - name of nearest enclosing function related to location of the marker
  mtid - string template ID used to produce value of msg field (only with fields=["*"])
  tool - name of SAST tool or component that created this marker (only with fields=["*"])
Response is capped by limit (default 30). If truncated:true appears, narrow filters
(severity/warnClass/file) or raise limit explicitly. total_count shows how many
markers matched before truncation.
Requires project_id, branch_id, snapshot_id — use get_projects then get_snapshots.\
"""

GET_PROJECT_STATS = """\
Get a statistical summary of warnings for a snapshot.

Returns warning counts grouped by severity (Critical/Major/Minor/Unspecified),
review status (Undecided/Confirmed/Won't fix/False Positive), and checker type.
Use before get_warnings or get_markers to understand scale and prioritize analysis.
Requires project_id, branch_id, snapshot_id — use get_projects then get_snapshots.\
"""

GET_PROJECT_GROUPS = """\
Get a project group by its name or UUID.

Project groups organize multiple projects into logical units (e.g. by team or product).
Returns project_group_id, project_group_name, and a 'projects' list where each item
has 'id' and 'name' fields. Use the project IDs with get_snapshots and other tools.\
"""

GET_ADVANCED_FILE_PREVIEW = """\
Retrieve a customizable preview of a file from a snapshot.

Typical use cases:
- got a warning with file and line from get_markers or get_warnings and want to get
  source code related to this position to understand the warning in context
- got a file_path and line when analyzing warnings and want to get source code
  related to a specific position to analyze it
Only requires snapshot_id and file_path (NOT project_id or branch_id).
Returns source lines around the specified center line.\
"""

GET_DIFF = """\
Compare two snapshots and show differences in markers.

Returns categories inside a top-level "markers" object: new_markers (added in
the newer snapshot), missing_markers (gone from the newer one), modified_markers
(same id, surrounding context changed), matched_markers (unchanged in both).
Only requires snapshot UUIDs — does NOT need project_id or branch_id.
Use get_projects + get_snapshots first to find snapshot UUIDs.
At level>=2 each category is wrapped into
{total_count, returned_count, truncated, markers} and capped independently by
limit (default 20 per category). Markers go through the same compact pipeline
as get_warnings — fields=["*"] yields the connector's known set (id, warnClass,
file, line, msg, tool, function, mtid, review, plus traces/checkerInfo when
requested), not arbitrary raw fields from the API.\
"""
