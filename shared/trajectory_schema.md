# Trajectory Artifact Schema

A batch is one invocation of a runner against one assignment plus optional filters.
Resuming a batch reuses the same batch directory and original metadata, skips
cases whose latest result is not retryable, appends missing or retry attempt
results, and rewrites the score summary from the latest result for each selected
case.

Student local artifacts live under `course_project/student_release/trajectories/{run_id}/`
by default. `run-tasks --output-root <path>` changes the parent output
directory: relative paths are resolved from `course_project/student_release/`,
and absolute paths are used directly. Staff artifacts may live elsewhere, but
should preserve the same file shapes inside each `{run_id}` batch directory.

Required files:

- `run_metadata.json`: run id, UTC timestamp, assignment id, split, backend, filters, selected cases, resume counters, and max worker count.
- `case_results.jsonl`: one JSON object per case attempt; a retried case can have multiple rows.
- `case_analysis.json`: benchmark/case-id indexed latest result summary for debugging and staff review.
- `score_summary.json`: aggregate grading scores, analysis scores, legacy reward aliases, and status counts.
- `cases/{benchmark}/{safe_case_key}/trajectory.jsonl`: request, response, tool result, score, and error events for the first attempt of that case.
- `cases/{benchmark}/{safe_case_key}/trajectory_llm_usage.jsonl`: optional per-attempt LLM usage sidecar when the student agent calls `CourseLLMClient`.

Retry attempts use `cases/{benchmark}/{safe_case_key}/attempt_{n}.jsonl`,
starting with `attempt_2.jsonl`; their optional LLM usage sidecars use
`attempt_{n}_llm_usage.jsonl`. `case_results.jsonl` keeps every attempt row;
`score_summary.json` and `case_analysis.json` use the latest result for each
selected case.

Case result objects include `run_id`, `benchmark`, `case_id`, `case_key`,
`status`, `grading_score`, `analysis_score`, `max_score`, `reward`,
`max_reward`, `backend`, `started_at`, `completed_at`, `trajectory_path`,
`attempt`, `auto_resumed`, LLM usage counters, and, for automatic retries,
`previous_status`.
`case_id` is the benchmark's official identifier; `case_key` is the short runner selector used in CLI commands and artifact paths.

LLM usage counters are populated when the student agent uses the provided
`CourseLLMClient`: `llm_api_call_count`, `llm_successful_call_count`,
`llm_failed_call_count`, `llm_prompt_tokens`, `llm_completion_tokens`,
`llm_total_tokens`, and `llm_estimated_input_tokens`. `llm_usage_path` is present
when a per-attempt usage sidecar exists. These fields do not include tau2's
benchmark-side user simulator LLM and are not guaranteed to include direct API
calls that bypass `CourseLLMClient`.

`grading_score` is the course grading value and is binary: `1.0` only when the
case is fully completed, otherwise `0.0`. `max_score` is always `1.0`.
`analysis_score` is feedback-only diagnostic information from the benchmark and
may use the benchmark's native scale. `reward` and `max_reward` are legacy
aliases kept for older tooling and currently mirror `grading_score` and
`max_score`.

Score events preserve the benchmark's original values when they differ from the
public grading fields: `raw_grading_score`, `raw_analysis_score`,
`raw_min_score`, and `raw_max_score`. Course grading should use
`grading_score`; analysis tooling may use `analysis_score` and raw score fields.

Status values:

- `scored_success`: the case completed and received full binary grading credit.
- `scored_failure`: the case ran to completion but did not receive full grading credit.
- `official_setup_error`: required benchmark checkout, package, service, or environment configuration is missing.
- `official_runtime_error`: the official benchmark environment failed while running.
- `student_runtime_error`: the student agent process or response contract failed at runtime.
- `runner_error`: the public runner itself failed outside the benchmark adapter.

`case_analysis.json` has this shape:

```json
{
  "run_id": "20260928_120000_public",
  "backend": "official",
  "generated_at": "2026-09-28T04:00:00Z",
  "benchmarks": {
    "mcpmark": {
      "filesystem/file_context/pattern_matching": {
        "case_key": "mcp_filesystem_file_context_pattern_matching",
        "status": "scored_failure",
        "analysis_score": 0.0,
        "grading_score": 0.0,
        "max_score": 1.0,
        "reward": 0.0,
        "max_reward": 1.0,
        "runtime_issue": false,
        "issue_category": "agent_performance",
        "issue_type": "agent_or_task_failure",
        "issue_message": "Case completed but did not reach full grading score.",
        "trajectory_path": "cases/mcpmark/mcp_filesystem_file_context_pattern_matching/trajectory.jsonl",
        "attempt": 1,
        "auto_resumed": false,
        "started_at": "2026-09-28T04:00:00Z",
        "completed_at": "2026-09-28T04:01:00Z",
        "llm_api_call_count": 2,
        "llm_successful_call_count": 2,
        "llm_failed_call_count": 0,
        "llm_prompt_tokens": 1200,
        "llm_completion_tokens": 300,
        "llm_total_tokens": 1500,
        "llm_estimated_input_tokens": 1250,
        "llm_usage_path": "cases/mcpmark/mcp_filesystem_file_context_pattern_matching/trajectory_llm_usage.jsonl"
      }
    }
  }
}
```

`runtime_issue` is `true` only for statuses ending in `_error`; a completed case
with `grading_score == 0.0` is classified as `agent_performance`, not a runtime
issue. `issue_category` is one of `none`, `agent_performance`,
`official_setup`, `official_runtime`, `student_runtime`, `runner`, `runtime`, or
`unknown`.

`score_summary.json` includes `selected_cases`, `completed_cases`,
`total_grading_score`, `average_grading_score`, `total_analysis_score`,
`average_analysis_score`, `total_reward`, `average_reward`, and
`status_counts`, plus aggregate LLM usage counters from the latest case results.
In the current runner, every case has weight `1.0`:
`total_grading_score` is the sum of binary per-case `grading_score` values, and
`average_grading_score` is `total_grading_score / completed_cases`. It is
written after all selected cases finish and after the single automatic retry for
runtime/setup errors, so it reflects the latest available result per selected
case.

LLM usage events appended to trajectories have `event: "llm_call"`, `status`,
`provider`, `model`, `deployment`, `attempt`, `estimated_input_tokens`, and a
`usage` object with API-returned token counts when available. The runner records
token totals, not currency cost; cost estimates require an external model price
table.

Assignment configs may include `scoring.baseline_anchors`. These anchors are
reference-only benchmark-level average scores measured from TA baseline-agent
runs on comparable public/hidden case sets. They are provided to contextualize
baseline difficulty.
