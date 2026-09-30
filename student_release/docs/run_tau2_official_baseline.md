# Run tau2 Official Baseline

This guide runs the student baseline agent against the real public tau2 airline
environment through the course public runner.

## 1. Install Student Dependencies

From `course_project/student_release`:

```bash
uv sync --locked
```

This installs the OpenAI SDK used by `course_agent.runtime.CourseLLMClient`.

## 2. Configure Local Environment

```bash
cp env.student.sh.example env.student.local.sh
```

Edit `env.student.local.sh`:

```bash
export COURSE_API_KEY="your-key"
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com"
export AZURE_OPENAI_API_VERSION="2025-02-01-preview"
export COURSE_LLM_MODEL="gpt-5-mini"
export AZURE_OPENAI_DEPLOYMENT="gpt-5-mini"
export TAU2_USER_MODEL="azure/gpt-4o-mini"
```

Then source it:

```bash
source env.student.local.sh
```

The baseline uses the same `COURSE_API_KEY` for the student agent and the tau2
user simulator, but different models.

`TAU2_USER_MODEL` uses LiteLLM's Azure provider prefix. If you set it to
`openai/gpt-4o-mini`, tau2 will call the public OpenAI API and will reject a
school Azure gateway key.

## 3. Install tau2-bench

From `course_project`:

```bash
bash third_party/setup_tau2_bench.sh
```

This creates `course_project/third_party/tau2-bench` and installs tau2's local
virtual environment.

## 4. Run One Public Case

From `course_project/student_release`:

```bash
uv run --locked python public_runner/run_public_tasks.py \
  --backend official \
  --case tau2_airline:tau2_49
```

Run another public case:

```bash
uv run --locked python public_runner/run_public_tasks.py \
  --backend official \
  --case tau2_airline:tau2_40
```

## 5. Inspect Results

Each run writes a batch under:

```text
trajectories/{run_id}/
```

Useful files:

```text
run_metadata.json
case_results.jsonl
score_summary.json
cases/tau2_airline/{case_key}/trajectory.jsonl
```

The case trajectory records the tau2 command, process output tail, parsed
official result, score, and any setup/runtime errors.

## Common Issues

- `The OpenAI SDK is not installed`: run `uv sync --locked`.
- `Tau2LLMEnvironmentError`: `COURSE_API_KEY`, `AZURE_OPENAI_ENDPOINT`, or
  `AZURE_OPENAI_API_VERSION` is missing or still set to the template
  placeholder; edit and source `env.student.local.sh`.
- `tau2-bench is not configured`: run `bash third_party/setup_tau2_bench.sh`
  from `course_project`.
- `Incorrect API key provided`: confirm `TAU2_USER_MODEL=azure/gpt-4o-mini`
  when using the school Azure gateway.
- `OpenAIException - Connection error`: check endpoint, API version, deployment,
  API key, and school network access.
