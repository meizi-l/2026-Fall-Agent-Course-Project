# Key Ownership Policy

There are two credential modes in the student release.

## Student Local

Students may copy `env.student.sh.example` to `env.student.local.sh` and put their own API key in that local file. The local env file is gitignored, rejected by `build_submission.py`, and never included in `submission.zip`.

Local official-public runs use the same HKUST GenAI `COURSE_API_KEY` for the student's agent and the environment user simulator. The models are separate: the student agent defaults to `gpt-5-mini`, while tau2's user simulator defaults to `openai/gpt-4o-mini`.

Both use `OPENAI_BASE_URL=https://hkust.azure-api.net/hkust-genai/v1`.
The `openai/` prefix selects LiteLLM's OpenAI-compatible protocol; the explicit
base URL selects the HKUST gateway. Course code adds the required `api-key`
header. Never put keys in `TAU2_USER_LLM_ARGS`, CLI arguments, or task JSON.

## Final Grading

Final grading uses staff/course-owned credentials injected by staff-side grading workers. The grader ignores student local env files, rejects submitted secrets, runs hidden official environments, and retains full staff artifacts for grading review.

Key material must not appear in trajectories, returned logs, score summaries,
case results, tracebacks, or retained grading artifacts.
