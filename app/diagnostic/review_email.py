"""Diagnostic review confirmation emails."""

from __future__ import annotations

import logging

from app.auth.email import _send_resend

logger = logging.getLogger(__name__)


async def send_diagnostic_submitted_email(*, to: str, name: str) -> bool:
    display = name.strip() or "there"
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#0f172a">
      <h1 style="font-size:20px;margin-bottom:12px">Your diagnostic has been received</h1>
      <p>Hi {display},</p>
      <p>Thanks for completing the BandForge free diagnostic. We received your Listening, Reading, Writing, and Speaking responses.</p>
      <p><strong>What happens next</strong></p>
      <ul>
        <li>Listening &amp; Reading — auto-scored bands are ready in your report</li>
        <li>Writing — AI-evaluated; your band is in your report now</li>
        <li>Speaking — a certified examiner will review your recording</li>
      </ul>
      <p>We will email your full band report with your Speaking score within 24–48 hours.</p>
      <p style="color:#64748b;font-size:13px;margin-top:24px">— BandForge Team</p>
    </div>
    """
    return await _send_resend(
        to=to,
        subject="BandForge diagnostic received — Speaking review in progress",
        html=html,
    )
