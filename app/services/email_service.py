# app/services/email_service.py
import re
import asyncio
import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SENDER_NAME   = "Safari Books Limited"
DEFAULT_SENDER_PHONE  = "07060603020"
DEFAULT_SENDER_EMAIL  = "safarinigeria@gmail.com"
DEFAULT_SENDER_EMAIL2 = "safaribk4jakpele@gmail.com"


def _wrap_html(
    body_html: str,
    sender_name: str = "",
    sender_phone: str = "",
    sender_email: str = "",
    sender_email2: str = "",
) -> str:

    sender_name   = sender_name   or DEFAULT_SENDER_NAME
    sender_phone  = sender_phone  or DEFAULT_SENDER_PHONE
    sender_email  = sender_email  or DEFAULT_SENDER_EMAIL
    sender_email2 = sender_email2 or DEFAULT_SENDER_EMAIL2

    AUTO_BOLD_TERMS = [
        'Safari Books Limited',
        'ProQuest',
        'Elsevier',
        'Springer Nature',
        'Wiley',
        'Harvard University',
        'University of Oxford',
        'Massachusetts Institute of Technology',
        'library development and book supply',
        'leading global universities',
    ]

    body_html = re.sub(r'\*\*(.+?)\*\*', r'\1', body_html)
    body_html = body_html.replace('—', ' - ')

    for term in sorted(AUTO_BOLD_TERMS, key=len, reverse=True):
        body_html = body_html.replace(term, f'<strong>{term}</strong>')

    body_html = re.sub(r'(<strong>)+' + re.escape('<strong>'), '<strong>', body_html)
    body_html = re.sub(r'(</strong>)+', '</strong>', body_html)

    body_html = re.sub(r'([^\n])\n?(For enquiries[^:]*:)', r'\1\n\n\2', body_html, flags=re.IGNORECASE)

    paragraphs = [p.strip() for p in body_html.replace('\r\n', '\n').split('\n\n') if p.strip()]

    body_paragraphs = ""
    for p in paragraphs:
        p_html = p.replace('\n', '<br/>')
        body_paragraphs += f'<p style="margin:0 0 14px 0;">{p_html}</p>\n'

    contact_lines = []
    if sender_phone:
        contact_lines.append(f'<p style="margin:4px 0;">📞 {sender_phone}</p>')

    if sender_email and sender_email2:
        contact_lines.append(
            f'<p style="margin:4px 0;">📧 '
            f'<a href="mailto:{sender_email}" style="color:#000000;text-decoration:none;">{sender_email}</a>'
            f' | '
            f'<a href="mailto:{sender_email2}" style="color:#000000;text-decoration:none;">{sender_email2}</a>'
            f'</p>'
        )
    elif sender_email:
        contact_lines.append(
            f'<p style="margin:4px 0;">📧 '
            f'<a href="mailto:{sender_email}" style="color:#000000;text-decoration:none;">{sender_email}</a>'
            f'</p>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
</head>
<body style="margin:0;padding:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#000000;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;">
    <tr><td style="padding:20px;">

      {body_paragraphs}

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
    sender_name: str = "",
    sender_phone: str = "",
    sender_email: str = "",
    sender_email2: str = "",
) -> bool:
    if not settings.SMTP_HOST or not settings.SMTP_USER:
        logger.warning("SMTP not configured — email not sent")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"]      = f"{to_name} <{to_email}>" if to_name else to_email

        if html_body.strip().lower().startswith("<!doctype") or html_body.strip().lower().startswith("<html"):
            full_html = html_body
        else:
            full_html = _wrap_html(
                body_html     = html_body,
                sender_name   = sender_name,
                sender_phone  = sender_phone,
                sender_email  = sender_email,
                sender_email2 = sender_email2,
            )

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
    <p>Hi {to_name},</p>
    <p><strong>{sender_name}</strong> mentioned you in <strong>#{channel_name}</strong>:</p>
    <p style="padding-left:16px;border-left:2px solid #000000;">{message_preview[:300]}</p>
    <p><a href="{app_url}/messages" style="color:#000000;">View Message</a></p>"""
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
    <p>Dear {to_name},</p>
    <p>We are pleased to invite you for an interview for the <strong>{position}</strong> position at <strong>{company_name}</strong>.</p>
    <p>
      Job Title: {position}<br/>
      Date: {interview_date}<br/>
      Time: {interview_time}<br/>
      Interviewer: {interviewer}
    </p>
    <p>Please confirm your availability by replying to this email. We look forward to speaking with you.</p>
    <p>Best regards,<br/>{company_name}</p>"""
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
    <p>Dear {to_name},</p>
    <p>We are delighted to offer you the position of <strong>{position}</strong> at <strong>{company_name}</strong>. After careful consideration of your application and interview performance, we are confident you will be a valuable addition to our team.</p>
    <p>
      Position: {position}<br/>
      Salary: {salary}<br/>
      Start Date: {start_date}
    </p>
    <p>Please review the terms and confirm your acceptance within 5 business days. We are excited to have you join our team!</p>
    <p>Best regards,<br/>{company_name}</p>"""
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
    <p>Dear {to_name},</p>
    <p>Thank you for your interest in the <strong>{position}</strong> position at <strong>{company_name}</strong> and for taking the time to go through our process.</p>
    <p>After careful consideration, we have decided to move forward with other candidates whose qualifications more closely match our current requirements.</p>
    <p>We appreciate your effort and encourage you to apply for future openings that match your skills and experience. We wish you the very best in your career journey.</p>
    <p>Best regards,<br/>{company_name}</p>"""
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
    date_str = datetime.utcnow().strftime("%B %d, %Y")
    rows = "".join(
        f"<p>{item['label']}: <strong>{item['value']}</strong></p>"
        for item in stats.get("items", [])
    )
    body = f"""
    <p>Hi {to_name},</p>
    <p>Here is your daily summary for {date_str}:</p>
    {rows}
    <p><a href="{app_url}/analytics" style="color:#000000;">View Full Analytics</a></p>"""
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
    severity: str = "info",
    app_url: str = "http://localhost:8000",
):
    label = {"info": "Info", "warning": "Warning", "critical": "Critical"}.get(severity, "Info")
    body = f"""
    <p>Hi {to_name},</p>
    <p><strong>[{label}] {title}</strong></p>
    <p>{message}</p>
    <p><a href="{app_url}" style="color:#000000;">Open BOSS</a></p>"""
    await send_email(
        to_email=to_email, to_name=to_name,
        subject=f"[{severity.upper()}] {title}",
        html_body=body,
    )


email_service = type("EmailService", (), {
    "send":       staticmethod(send_email),
    "mention":    staticmethod(send_mention_notification),
    "hr":         staticmethod(send_hr_email),
    "interview":  staticmethod(send_interview_invite),
    "offer":      staticmethod(send_offer_letter),
    "rejection":  staticmethod(send_rejection_email),
    "digest":     staticmethod(send_daily_digest),
    "alert":      staticmethod(send_alert),
})()