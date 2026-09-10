import json
import urllib.request
from typing import Optional

OLLAMA_BASE = "http://localhost:11434"


class OllamaError(Exception):
    pass


def chat(messages: list, model: str, base: str = OLLAMA_BASE, timeout: int = 120) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
    }
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["message"]["content"]


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
    raise OllamaError(f"Could not parse JSON from LLM response: {text[:200]}")


def is_job_board(page_text: str, model: str, base: str = OLLAMA_BASE) -> Optional[dict]:
    """Step 2: validate the page is not a job board/aggregator listing.

    Returns {"is_job_board": bool, "reason": str}, or None if LLM is unreachable.
    """
    prompt = (
        "You are triaging a webpage fetched from a career search.\n"
        "Decide whether the page is a JOB BOARD / AGGREGATOR listing "
        "(e.g. indeed.com, ziprecruiter.com, glassdoor.com, simplyhired, monster, "
        "careers pages that merely link out to multiple external postings) "
        "rather than the employer's OWN concrete job posting with a description.\n"
        "Respond with JSON: {\"is_job_board\": true|false, \"reason\": \"<one short sentence>\"}"
    )
    try:
        raw = chat(
            [
                {"role": "user", "content": f"{prompt}\n\n---PAGE TEXT---\n{page_text[:8000]}"},
            ],
            model=model,
            base=base,
        )
        return parse_json(raw)
    except Exception:
        return None


def resume_fit(resume_text: str, page_text: str, model: str, base: str = OLLAMA_BASE) -> Optional[dict]:
    """Step 3: assess how well the job posting matches the resume.

    Returns {"match": bool, "score": int, "reason": str}, or None if LLM is unreachable.
    """
    prompt = (
        "You are a hiring recruiter. Compare the candidate's resume with a job posting "
        "fetched from a career search.\n"
        "Assess how well the candidate's experience, skills, and seniority fit the job.\n"
        "Respond with JSON: "
        "{\"match\": true|false, \"score\": <integer 0-100>, \"reason\": \"<one or two short sentences>\"}\n"
        "Set match=true only if the fit is strong (score >= 60)."
    )
    try:
        raw = chat(
            [
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        f"---RESUME---\n{resume_text[:6000]}\n\n"
                        f"---JOB POSTING---\n{page_text[:8000]}"
                    ),
                },
            ],
            model=model,
            base=base,
        )
        return parse_json(raw)
    except Exception:
        return None


def ollama_available(base: str = OLLAMA_BASE) -> bool:
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def trim_text(text: str, limit: int = 8000) -> str:
    return text[:limit]
