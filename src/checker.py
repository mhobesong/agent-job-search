import re
from dataclasses import dataclass, field
from typing import List

REMOTE_PATTERNS = [
    r"\bremote\b",
    r"\bwork from home\b",
    r"\bwfh\b",
    r"\bfully remote\b",
    r"\banywhere in (the )?world\b",
    r"\blocation independent\b",
]
REMOTE_RE = re.compile("|".join(REMOTE_PATTERNS), re.IGNORECASE)


@dataclass
class CheckResult:
    url: str
    text: str
    skills_matched: List[str] = field(default_factory=list)
    skills_missing: List[str] = field(default_factory=list)
    remote_found: bool = False
    passed: bool = False
    reason: str = ""


def normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text).lower()
    return text


def check_page(url: str, text: str, skills: List[str], require_remote: bool, min_skill_match: int) -> CheckResult:
    """Step 1: deterministic skill + remote matching against page text."""
    norm = normalize(text)

    matched, missing = [], []
    for skill in skills:
        pattern = re.escape(skill.lower())
        if re.search(rf"\b{pattern}\b", norm):
            matched.append(skill)
        else:
            missing.append(skill)

    remote_found = bool(REMOTE_RE.search(text))

    passed = len(matched) >= min_skill_match
    if require_remote and not remote_found:
        passed = False

    reasons = [f"{len(matched)}/{len(skills)} skills matched"]
    if require_remote:
        reasons.append("remote " + ("found" if remote_found else "NOT found"))
    result = CheckResult(
        url=url,
        text=text,
        skills_matched=matched,
        skills_missing=missing,
        remote_found=remote_found,
        passed=passed,
        reason="; ".join(reasons),
    )
    return result
