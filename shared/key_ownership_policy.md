# Key Ownership Policy

There are two credential modes in the student release.

## Student Local

Students may copy `env.student.sh.example` to `env.student.local.sh` and put their own API key in that local file. The local env file is gitignored, rejected by `build_submission.py`, and never included in `submission.zip`.

Local official-public runs use the same `COURSE_API_KEY` for the student's agent and the environment user simulator. The models are separate: the student agent defaults to `gpt-5-mini`, while tau2's user simulator defaults to `azure/gpt-4o-mini`.

For the HKUST/Azure gateway, tau2 must use LiteLLM's Azure provider prefix. `openai/gpt-4o-mini` routes to the public OpenAI API and will reject the school gateway key.

## Final Grading

Final grading uses staff/course-owned credentials injected by staff-side grading workers. The grader ignores student local env files, rejects submitted secrets, runs hidden official environments, and retains full staff artifacts for grading review.

Key material must not appear in trajectories, returned logs, score summaries,
case results, tracebacks, or retained grading artifacts.
