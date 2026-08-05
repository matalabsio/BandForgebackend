"""Privacy-safe notification templates."""

from html import escape
from urllib.parse import quote


def speaking_report_url(
    frontend_url: str, attempt_id: str, test_number: int | None = None
) -> str:
    encoded_attempt = quote(attempt_id, safe="")
    if test_number is not None and test_number > 0:
        return (
            f"{frontend_url.rstrip('/')}/test/{test_number}/speaking/results"
            f"?attempt={encoded_attempt}"
        )
    return (
        f"{frontend_url.rstrip('/')}/test/speaking/results/{encoded_attempt}"
    )


def speaking_release_email_html(
    *, student_name: str | None, examiner_name: str | None, report_url: str
) -> str:
    name = escape((student_name or "there").strip())
    examiner = escape((examiner_name or "").strip())
    safe_url = escape(report_url, quote=True)
    examiner_line = (
        f"<p>Your report was reviewed by {examiner}.</p>" if examiner else ""
    )
    return (
        '<div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;">'
        "<h1>Your Speaking report is ready</h1>"
        f"<p>Hi {name},</p>"
        "<p>Your examiner-reviewed Speaking report is now available.</p>"
        f"{examiner_line}"
        f'<p><a href="{safe_url}">View your authenticated report</a></p>'
        "<p>Sign in to BandForge to access it securely.</p>"
        "</div>"
    )


def speaking_release_whatsapp_components(
    *, student_name: str | None, report_url: str
) -> list[dict[str, object]]:
    return [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": (student_name or "Student").strip()},
                {"type": "text", "text": report_url},
            ],
        }
    ]


def plan_today_url(frontend_url: str) -> str:
    return f"{frontend_url.rstrip('/')}/study-plan/today"


def plan_reminder_email_html(
    *,
    student_name: str | None,
    unfinished_count: int,
    today_url: str,
    task_titles: list[str] | None = None,
) -> str:
    name = escape((student_name or "there").strip())
    safe_url = escape(today_url, quote=True)
    count = max(0, int(unfinished_count))
    noun = "task" if count == 1 else "tasks"
    titles = [t.strip() for t in (task_titles or []) if isinstance(t, str) and t.strip()]
    list_html = ""
    if titles:
        items = "".join(f"<li>{escape(t[:120])}</li>" for t in titles[:5])
        list_html = f"<ul>{items}</ul>"
    return (
        '<div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;">'
        "<h1>Your BandForge practice plan is waiting</h1>"
        f"<p>Hi {name},</p>"
        f"<p>You still have {count} unfinished {noun} on today's study plan.</p>"
        f"{list_html}"
        f'<p><a href="{safe_url}">Open Today&rsquo;s plan</a></p>'
        "<p>A short session keeps your streak and weekly goals on track.</p>"
        "</div>"
    )
