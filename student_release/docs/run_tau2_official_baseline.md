# Run tau2 Official Tasks

This guide runs your implemented StudentAgent against the real public tau2
airline environment through the course public runner. The starter template
returns placeholders; it does not provide a benchmark-solving baseline.

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
export COURSE_API_KEY="your-hkust-genai-key"
export OPENAI_BASE_URL="https://hkust.azure-api.net/hkust-genai/v1"
export COURSE_LLM_MODEL="gpt-5-mini"
export TAU2_USER_MODEL="openai/gpt-4o-mini"
```

Then source it:

```bash
source env.student.local.sh
```

Local runs use the same `COURSE_API_KEY` for the student agent and the tau2
user simulator, but different models.

Only the API key needs replacing in the provided template. Use a key subscribed
to HKUST GenAI with access to both models. `openai/` selects LiteLLM's
OpenAI-compatible protocol; `OPENAI_BASE_URL` directs it to HKUST. Course code
adds the required `api-key` header without putting it in logged LLM arguments.

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
- `Tau2LLMEnvironmentError`: `COURSE_API_KEY` or `OPENAI_BASE_URL` is missing,
  or the key is still set to the template
  placeholder; edit and source `env.student.local.sh`.
- `tau2-bench is not configured`: run `bash third_party/setup_tau2_bench.sh`
  from `course_project`.
- Authentication/model errors: confirm the HKUST GenAI subscription and model
  access. Keep `TAU2_USER_MODEL=openai/gpt-4o-mini` and the provided base URL.
- `OpenAIException - Connection error`: check the base URL and network access.
