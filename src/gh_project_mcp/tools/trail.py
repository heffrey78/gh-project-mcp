"""The comments the server writes, and how it recognises them again (REQ-0006-FUNC-00).

GitHub's timeline is the history. These comments put the reasoning on it: why a status moved and on what evidence,
why an approved requirement was edited, and what was later corrected in a decided decision.
"""

from ..github.port import Comment

STATUS_MARK = "**Status:**"
EDIT_MARK = "**Edited:**"
AMENDMENT_MARK = "**Amendment**"
SUPERSEDED_MARK = "**Superseded by**"
REASON_MARK = "**Reason:**"
ARROW = " → "


def status_comment(path: list[str], comment: str | None, commit: str | None, evidence: str | None) -> str:
    lines = [f"{STATUS_MARK} {ARROW.join(path)}"]
    if commit:
        lines.append(f"**Commit:** {commit}")
    if evidence:
        lines.append(f"**Evidence:** {evidence}")
    if comment:
        lines += ["", comment.strip()]
    return "\n".join(lines)


def edit_comment(changed: list[str], reason: str) -> str:
    return f"{EDIT_MARK} {', '.join(changed)}\n\n{reason.strip()}"


def amendment_comment(text: str, reason: str | None) -> str:
    body = f"{AMENDMENT_MARK}\n\n{text.strip()}"
    return body + (f"\n\n{REASON_MARK} {reason.strip()}" if reason else "")


def amendments(comments: list[Comment]) -> list[Comment]:
    """The comments that correct a decided decision, oldest first."""
    return [c for c in comments if c.body.lstrip().startswith(AMENDMENT_MARK)]


def amendment_text(comment: Comment) -> str:
    """An amendment as one dated, attributed line, for details and export."""
    text, _, reason = comment.body.lstrip()[len(AMENDMENT_MARK) :].partition(REASON_MARK)
    line = f"Amendment ({comment.created_at[:10]}, {comment.author}): {' '.join(text.split())}"
    return line + (f" Reason: {' '.join(reason.split())}" if reason.strip() else "")
