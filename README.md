# Job Search Agent

A Python agent that searches Google for career pages matching your skills,
filters results deterministically, validates them with a local LLM (Ollama),
and ranks them by fit against your resume.

## How it works

Given your resume, a list of skills, and an `--remote` flag, the agent:

1. Builds a Google search query, e.g.:
   ```
   intitle:career AND "python" AND "sql" AND "aws" AND "remote" -site:facebook.com -site:linkedin.com
   ```
2. Walks up to **2 Google result listing pages** (Playwright/Chromium) and
   collects candidate URLs.
3. For each candidate page, in order:
   - **Step 1 — deterministic match (no LLM):** checks the page text against
     your skills list (word-boundary match) and for remote keywords
     (`remote`, `work from home`, `wfh`, ...). Pages that don't hit the
     minimum skill threshold — or lack "remote" when `--remote` is set — are
     skipped.
   - **Step 2 — LLM (Ollama):** asks the model whether the page is a job
     board / aggregator listing (Indeed, ZipRecruiter, Glassdoor, ...)
     instead of the employer's own posting. If yes, the page is skipped.
   - **Step 3 — LLM (Ollama):** scores how well the candidate's resume fits
     the posting (0–100) and whether to keep it.
4. Prints a console report and writes `results.json`.

## Requirements

- Python 3.9+
- [Ollama](https://ollama.com) running locally (default `http://localhost:11434`)
  with a model pulled, e.g. `ollama pull llama3.1`
  (any instruct model works — change with `--model`)
- A resume file (`.pdf`, `.txt`, or `.md`)

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

Make sure Ollama is running:

```bash
ollama serve        # if not running
ollama pull llama3.1
```

## Usage

```bash
python agent.py \
  --resume Resume.pdf \
  --skills "python,sql,aws" \
  --remote
```

## Web Interface

A local web interface is available to launch searches and monitor progress in real-time.

```bash
python -m web
```

Accessible at `http://127.0.0.1:8000`. Features include:
- Live progress bar and event log.
- File upload for resumes.
- Light/Dark mode toggle.
- Active run cancellation.

Print just the query without running:

```bash
python agent.py --resume Resume.pdf --skills "python,sql" --list
```

### Options

| Flag | Default | Description |
| --- | --- | --- |
| `--resume` | — *(required)* | Path to the resume file (`.pdf`, `.txt`, `.md`) |
| `--skills` | — *(required)* | Comma-separated skills |
| `--remote` | off | Require remote / work-from-home postings in the search and on the page |
| `--max-pages` | `2` | Number of Google listing pages to walk |
| `--min-skill-match` | majority of skills | Minimum skills that must appear on the page |
| `--model` | `llama3.1` | Ollama model name |
| `--no-llm` | off | Skip LLM steps 2 & 3 (deterministic match only) |
| `--headless` | off | Run Chromium headless (forced off — captcha escalation needs a visible browser) |
| `--captcha-wait` | `120` | Seconds to wait for a human to solve a captcha before skipping the URL/page |
| `--google-domain` | `google.com` | e.g. `google.co.il` to avoid region issues |
| `--output` | `results.json` | Output JSON path |
| `--list` | off | Print the search query and exit |

## Output

- Console table of every candidate examined:
  URL, skills matched, remote, fit score, and status
   (`MATCH`, `rejected:match`, `rejected:job_board`, `fetch-failed`,
   `skipped:captcha`, `review`).
- `results.json` with the full trail: query, timestamps, per-page
  details, skill breakdown, fit score, and reasons.

Example:

```json
{
  "generated_at": "2026-09-09T18:00:00+00:00",
  "query": "intitle:career \"python\" AND \"sql\" AND \"aws\" AND \"remote\" ...",
  "matches": ["https://acme.com/careers/python-infra"],
  "results": [
    {
      "url": "https://acme.com/careers/python-infra",
      "matched": true,
      "skills_matched": ["python", "sql", "aws"],
      "remote_found": true,
      "fit_score": 82,
      "fit_reason": "Strong fit on backend and cloud skills."
    }
  ]
}
```

## Project layout

```
agent.py           CLI entrypoint and main loop
src/runner.py      Search pipeline and event emission
src/search.py      Playwright Google search + candidate page fetch
src/checker.py     Step 1: deterministic skill/remote matching
src/llm.py         Ollama client for steps 2 & 3
src/resume.py      Resume text extraction (pdfplumber)
src/report.py      Console table + results.json
web/               Web interface (FastAPI + Vanilla JS)
requirements.txt
```

## Notes & troubleshooting

- **Google consent page / captcha:** the agent runs headed and detects
  reCAPTCHA/hCaptcha (including Google's "unusual traffic" page). When one
  appears it beeps, prints a banner with the URL, and waits for you to solve
  it in the browser — up to `--captcha-wait` seconds (default 120). If it is
  not solved in time, that URL (or listing page) is skipped and the run
  continues. Passing `--headless` is rejected because you cannot solve a
  captcha in a window you cannot see.
- **Ollama not reachable:** the agent warns and falls back to the
  deterministic match only; use `--no-llm` to silence the warning.
- **No results after 2 pages:** that's by design — the agent stops after the
  configured number of listing pages (`--max-pages`).
- Add more sites to `EXCLUDED_SITES` in `src/search.py` if you see noisy
  aggregators leaking through.
