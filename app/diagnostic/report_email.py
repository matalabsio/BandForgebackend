"""Diagnostic full report card emails."""

from __future__ import annotations

from typing import Any

from app.auth.email import _send_resend
from app.config import get_settings


def _band_cell(label: str, band: float | None) -> str:
    value = f"{band:.1f}" if band is not None else "—"
    return f"""
    <td style="padding:12px 16px;text-align:center;border:1px solid #E8EDF3;">
      <div style="font-size:11px;color:#94A3B8;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px;">{label}</div>
      <div style="font-size:22px;font-weight:600;color:#0D1F3C;font-family:ui-monospace,monospace;">{value}</div>
    </td>
    """


def _bullet_list(items: list[str]) -> str:
    if not items:
        return ""
    lis = "".join(f'<li style="margin-bottom:6px;">{item}</li>' for item in items)
    return f'<ul style="margin:8px 0 0 18px;padding:0;color:#475569;font-size:14px;line-height:1.5;">{lis}</ul>'


async def send_diagnostic_report_email(
    *,
    to: str,
    name: str,
    goal_label: str | None,
    target_band: float | None,
    listening_band: float | None,
    reading_band: float | None,
    writing_band: float | None,
    speaking_band: float | None,
    aggregate_band: float | None,
    writing_feedback: dict[str, Any] | None,
    speaking_notes: str | None,
) -> bool:
    display = name.strip() or "there"
    goal_line = (
        f'<p style="color:#5A6B82;font-size:14px;margin:0 0 16px;">Goal: <strong style="color:#0D1F3C;">{goal_label}</strong>'
        + (
            f' · Target band <strong style="color:#0097A7;">{target_band:.1f}</strong>'
            if target_band is not None
            else ""
        )
        + "</p>"
        if goal_label
        else ""
    )

    overall_line = (
        f'<p style="font-size:16px;color:#0D1F3C;margin:0 0 20px;">Estimated overall band: '
        f'<strong style="color:#00BCD4;font-size:24px;font-family:ui-monospace,monospace;">{aggregate_band:.1f}</strong></p>'
        if aggregate_band is not None
        else ""
    )

    writing_section = ""
    if writing_feedback:
        tips: list[str] = []
        for key in ("strengths", "weaknesses", "improvement_tips"):
            raw = writing_feedback.get(key)
            if isinstance(raw, list):
                tips.extend(str(x) for x in raw[:3])
        if tips:
            writing_section = f"""
            <div style="margin-top:20px;padding:16px;background:#F8FAFC;border-radius:12px;border:1px solid #E8EDF3;">
              <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#0D1F3C;">Writing feedback</p>
              {_bullet_list(tips[:6])}
            </div>
            """

    speaking_section = ""
    if speaking_notes and speaking_notes.strip():
        speaking_section = f"""
        <div style="margin-top:16px;padding:16px;background:#F8FAFC;border-radius:12px;border:1px solid #E8EDF3;">
          <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#0D1F3C;">Speaking examiner notes</p>
          <p style="margin:8px 0 0;color:#475569;font-size:14px;line-height:1.55;">{speaking_notes.strip()}</p>
        </div>
        """

    plan_url = f"{get_settings().frontend_url.rstrip('/')}/diagnostic/plan"
    subject_band = f" — Band {aggregate_band:.1f} overall" if aggregate_band is not None else ""

    html = f"""
    <div style="font-family:system-ui,-apple-system,sans-serif;max-width:560px;margin:0 auto;color:#0f172a;padding:8px;">
      <h1 style="font-size:22px;color:#0D1F3C;margin:0 0 8px;">Your BandForge diagnostic report</h1>
      <p style="color:#5A6B82;font-size:15px;line-height:1.5;margin:0 0 16px;">Hi {display}, here is your full band report across all four IELTS skills.</p>
      {goal_line}
      {overall_line}
      <table style="width:100%;border-collapse:collapse;border-radius:12px;overflow:hidden;margin-bottom:8px;">
        <tr>
          {_band_cell("Listening", listening_band)}
          {_band_cell("Reading", reading_band)}
        </tr>
        <tr>
          {_band_cell("Writing", writing_band)}
          {_band_cell("Speaking", speaking_band)}
        </tr>
      </table>
      {writing_section}
      {speaking_section}
      <p style="margin:28px 0 16px;text-align:center;">
        <a href="{plan_url}" style="display:inline-block;background:#00BCD4;color:#fff;padding:14px 28px;border-radius:999px;text-decoration:none;font-weight:600;font-size:15px;">View your personalised study plan</a>
      </p>
      <p style="color:#94A3B8;font-size:12px;text-align:center;margin-top:24px;">— BandForge Team</p>
    </div>
    """

    return await _send_resend(
        to=to,
        subject=f"Your BandForge diagnostic report{subject_band}",
        html=html,
    )
