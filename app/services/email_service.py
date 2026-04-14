# app/services/email_service.py
"""
1. Email Integration (SMTP)
Handles all outbound email for BOSS:
  - HR notifications (offer letters, interview invites, rejection)
  - @Mention notifications
  - Audit alerts
  - Daily/weekly digest
  - General system alerts
"""

import asyncio
import logging
import smtplib
import ssl
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

def _wrap_html(subject: str, body_html: str, footer: str = "") -> str:
    """Wrap content in a branded BOSS HTML email shell."""
    accent = "#dc2626"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:40px 20px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Header -->
        <tr><td style="background:#18181b;border-radius:10px 10px 0 0;padding:24px 32px;">
          <table width="100%"><tr>
            <td><span style="font-family:monospace;font-weight:800;font-size:20px;color:{accent};letter-spacing:-0.5px;">BOSS</span>
            <span style="font-size:13px;color:#71717a;margin-left:10px;">Business Operating System</span></td>
          </tr></table>
        </td></tr>

        <!-- Body -->
        <tr><td style="background:#ffffff;padding:32px;border-left:1px solid #e4e4e7;border-right:1px solid #e4e4e7;">
          {body_html}
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#f8f8f8;border:1px solid #e4e4e7;border-top:none;border-radius:0 0 10px 10px;
            padding:16px 32px;text-align:center;font-size:11px;color:#a1a1aa;">
          {footer or 'This email was sent by BOSS System · <a href="#" style="color:#a1a1aa;">Unsubscribe</a>'}
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    to_name: str = "",
    text_body: str = "",
) -> bool:
    """Send a single email via SMTP. Returns True on success."""
    if not settings.SMTP_HOST or not settings.SMTP_USER:
        logger.warning("SMTP not configured — email not sent")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"]      = f"{to_name} <{to_email}>" if to_name else to_email

        full_html = _wrap_html(subject, html_body)
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(full_html, "html"))

        def _send():
            context = ssl.create_default_context()
            if settings.SMTP_PORT == 465:
                with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as s:
                    s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as s:
                    s.ehlo()
                    s.starttls(context=context)
                    s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    s.send_message(msg)
        await asyncio.get_event_loop().run_in_executor(None, _send)
        logger.info(f"Email sent to {to_email}: {subject}")
        return True

    except Exception as e:
        logger.error(f"Email send failed to {to_email}: {e}")
        return False

async def send_mention_notification(
    to_email: str,
    to_name: str,
    sender_name: str,
    channel_name: str,
    message_preview: str,
    app_url: str = "http://localhost:8000",
):
    body = f"""
    <h2 style="font-size:20px;font-weight:700;color:#18181b;margin:0 0 8px;">
      You were mentioned 💬
    </h2>
    <p style="color:#52525b;font-size:14px;margin:0 0 24px;">
      <strong>{sender_name}</strong> mentioned you in <strong>#{channel_name}</strong>
    </p>
    <div style="background:#f4f4f5;border-left:3px solid #dc2626;border-radius:6px;
        padding:16px;margin:0 0 24px;font-size:14px;color:#18181b;line-height:1.6;">
      {message_preview[:300]}
    </div>
    <a href="{app_url}/messages" style="display:inline-block;background:#18181b;color:#fff;
        padding:12px 28px;border-radius:7px;text-decoration:none;font-weight:600;font-size:14px;">
      View Message →
    </a>"""
    await send_email(
        to_email=to_email, to_name=to_name,
        subject=f"{sender_name} mentioned you in #{channel_name}",
        html_body=body,
    )


async def send_hr_email(
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
):
    """Generic HR email (offer, interview invite, rejection, etc.)."""
    await send_email(to_email=to_email, to_name=to_name, subject=subject, html_body=body_html)


async def send_interview_invite(
    to_email: str,
    to_name: str,
    position: str,
    interview_date: str,
    interview_time: str,
    interviewer: str,
    company_name: str = "Our Company",
    app_url: str = "http://localhost:8000",
):
    body = f"""
    <h2 style="font-size:20px;font-weight:700;color:#18181b;margin:0 0 8px;">
      Interview Invitation 🎯
    </h2>
    <p style="color:#52525b;font-size:14px;margin:0 0 20px;">
      Dear <strong>{to_name}</strong>, we are pleased to invite you for an interview for the
      <strong>{position}</strong> position at <strong>{company_name}</strong>.
    </p>
    <table style="background:#f4f4f5;border-radius:8px;padding:20px;width:100%;border-collapse:collapse;">
      <tr><td style="padding:8px 0;font-size:13px;color:#71717a;width:140px;">Position</td>
          <td style="padding:8px 0;font-size:13px;font-weight:600;color:#18181b;">{position}</td></tr>
      <tr><td style="padding:8px 0;font-size:13px;color:#71717a;">Date</td>
          <td style="padding:8px 0;font-size:13px;font-weight:600;color:#18181b;">{interview_date}</td></tr>
      <tr><td style="padding:8px 0;font-size:13px;color:#71717a;">Time</td>
          <td style="padding:8px 0;font-size:13px;font-weight:600;color:#18181b;">{interview_time}</td></tr>
      <tr><td style="padding:8px 0;font-size:13px;color:#71717a;">Interviewer</td>
          <td style="padding:8px 0;font-size:13px;font-weight:600;color:#18181b;">{interviewer}</td></tr>
    </table>
    <p style="color:#52525b;font-size:13px;margin:20px 0;">
      Please confirm your availability by replying to this email.
      We look forward to speaking with you.
    </p>"""
    await send_email(
        to_email=to_email, to_name=to_name,
        subject=f"Interview Invitation — {position} at {company_name}",
        html_body=body,
    )


async def send_offer_letter(
    to_email: str,
    to_name: str,
    position: str,
    salary: str,
    start_date: str,
    company_name: str = "Our Company",
):
    body = f"""
    <h2 style="font-size:22px;font-weight:800;color:#18181b;margin:0 0 8px;">
      Congratulations! 🎉
    </h2>
    <p style="color:#52525b;font-size:14px;margin:0 0 20px;line-height:1.7;">
      Dear <strong>{to_name}</strong>,<br><br>
      We are delighted to offer you the position of <strong>{position}</strong> at
      <strong>{company_name}</strong>. After careful consideration of your application and
      interview performance, we are confident you will be a valuable addition to our team.
    </p>
    <table style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:20px;width:100%;border-collapse:collapse;">
      <tr><td style="padding:8px 0;font-size:13px;color:#166534;width:140px;">Position</td>
          <td style="padding:8px 0;font-size:13px;font-weight:700;color:#166534;">{position}</td></tr>
      <tr><td style="padding:8px 0;font-size:13px;color:#166534;">Salary</td>
          <td style="padding:8px 0;font-size:13px;font-weight:700;color:#166534;">{salary}</td></tr>
      <tr><td style="padding:8px 0;font-size:13px;color:#166534;">Start Date</td>
          <td style="padding:8px 0;font-size:13px;font-weight:700;color:#166534;">{start_date}</td></tr>
    </table>
    <p style="color:#52525b;font-size:13px;margin:20px 0 0;line-height:1.7;">
      Please review the terms and confirm your acceptance within 5 business days.
      We are excited to have you join our team!
    </p>"""
    await send_email(
        to_email=to_email, to_name=to_name,
        subject=f"Offer Letter — {position} at {company_name}",
        html_body=body,
    )


async def send_rejection_email(
    to_email: str,
    to_name: str,
    position: str,
    company_name: str = "Our Company",
):
    body = f"""
    <h2 style="font-size:18px;font-weight:700;color:#18181b;margin:0 0 12px;">
      Application Update
    </h2>
    <p style="color:#52525b;font-size:14px;line-height:1.7;margin:0 0 16px;">
      Dear <strong>{to_name}</strong>,<br><br>
      Thank you for your interest in the <strong>{position}</strong> position at
      <strong>{company_name}</strong> and for taking the time to go through our process.
    </p>
    <p style="color:#52525b;font-size:14px;line-height:1.7;margin:0 0 16px;">
      After careful consideration, we have decided to move forward with other candidates
      whose qualifications more closely match our current requirements.
    </p>
    <p style="color:#52525b;font-size:14px;line-height:1.7;margin:0;">
      We appreciate your effort and encourage you to apply for future openings that match
      your skills and experience. We wish you the very best in your career journey.
    </p>"""
    await send_email(
        to_email=to_email, to_name=to_name,
        subject=f"Re: Your Application — {position}",
        html_body=body,
    )


async def send_daily_digest(
    to_email: str,
    to_name: str,
    stats: dict,
    app_url: str = "http://localhost:8000",
):
    """Daily activity digest for managers."""
    date_str = datetime.utcnow().strftime("%B %d, %Y")
    rows = "".join(f"""
      <tr>
        <td style="padding:10px 16px;font-size:13px;color:#52525b;">{item['label']}</td>
        <td style="padding:10px 16px;font-size:14px;font-weight:700;color:#18181b;text-align:right;">{item['value']}</td>
      </tr>""" for item in stats.get("items", []))

    body = f"""
    <h2 style="font-size:20px;font-weight:700;color:#18181b;margin:0 0 4px;">Daily Digest</h2>
    <p style="color:#a1a1aa;font-size:13px;margin:0 0 24px;">{date_str}</p>
    <table style="width:100%;border-collapse:collapse;border:1px solid #e4e4e7;border-radius:8px;overflow:hidden;">
      <thead><tr style="background:#f4f4f5;">
        <th style="padding:10px 16px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#71717a;">Metric</th>
        <th style="padding:10px 16px;text-align:right;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#71717a;">Today</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <div style="margin-top:24px;">
      <a href="{app_url}/analytics" style="display:inline-block;background:#18181b;color:#fff;
          padding:11px 24px;border-radius:7px;text-decoration:none;font-weight:600;font-size:13px;">
        View Full Analytics →
      </a>
    </div>"""
    await send_email(
        to_email=to_email, to_name=to_name,
        subject=f"BOSS Daily Digest — {date_str}",
        html_body=body,
    )


async def send_alert(
    to_email: str,
    to_name: str,
    title: str,
    message: str,
    severity: str = "info",   # info | warning | critical
    app_url: str = "http://localhost:8000",
):
    colors = {"info": "#2563eb", "warning": "#d97706", "critical": "#dc2626"}
    color = colors.get(severity, "#2563eb")
    icon  = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(severity, "ℹ️")
    body = f"""
    <div style="border-left:4px solid {color};padding:16px 20px;background:{color}10;border-radius:0 8px 8px 0;margin-bottom:20px;">
      <div style="font-size:16px;font-weight:700;color:#18181b;margin-bottom:6px;">{icon} {title}</div>
      <div style="font-size:13px;color:#52525b;line-height:1.6;">{message}</div>
    </div>
    <a href="{app_url}" style="display:inline-block;background:#18181b;color:#fff;
        padding:10px 22px;border-radius:7px;text-decoration:none;font-weight:600;font-size:13px;">
      Open BOSS →
    </a>"""
    await send_email(
        to_email=to_email, to_name=to_name,
        subject=f"[{severity.upper()}] {title}",
        html_body=body,
    )

email_service = type("EmailService", (), {
    "send": staticmethod(send_email),
    "mention": staticmethod(send_mention_notification),
    "hr": staticmethod(send_hr_email),
    "interview": staticmethod(send_interview_invite),
    "offer": staticmethod(send_offer_letter),
    "rejection": staticmethod(send_rejection_email),
    "digest": staticmethod(send_daily_digest),
    "alert": staticmethod(send_alert),
})()