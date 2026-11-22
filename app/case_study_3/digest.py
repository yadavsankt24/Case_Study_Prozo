"""
Daily digest: one colour-coded message per FC for one date, and its delivery.

Building the digest
    headline (colour + CM2), the key numbers, the insight, top contributors,
    trend from memory (e.g. "3 Red days in a row") and the recommended action.
    Rendered as email-safe HTML (inline styles) plus a plain-text version.

Delivery (real channel = email)
    EmailNotifier   any SMTP server, e.g. Gmail with an app password
    OutboxNotifier  used when SMTP is not configured: saves the digest as an .html
                    file in storage/cs3_outbox/ so the flow can be demonstrated offline
"""

from __future__ import annotations

import csv
import html
import logging
import smtplib
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from app.config import Settings
from app.case_study_3 import rules
from app.case_study_3.insights import rupees, trend_sentence
from app.case_study_3.models import Colour, Trend

log = logging.getLogger(__name__)

COLOURS = {
    "Red": ("#b42318", "#fbe4e2"),
    "Yellow": ("#8a5a00", "#fff3d6"),
    "Green": ("#1e6b37", "#e3f4e8"),
    "Blue": ("#1d5fa8", "#e3eefb"),
}


@dataclass
class Digest:
    fc: str
    day: str
    colour: str
    subject: str
    text: str
    html: str
    recipient: str
    manager: str
    insight_mode: str          # "template" or "llm:<provider>"


@dataclass
class Delivery:
    channel: str               # "email" or "outbox"
    status: str                # "sent", "saved" or "failed"
    detail: str


# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------

def load_managers(path: Path) -> dict[str, dict]:
    """fc,manager,email  ->  {fc: {"manager": ..., "email": ...}}"""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return {row["fc"].strip(): {"manager": row.get("manager", "").strip(), "email": row.get("email", "").strip()}
                for row in csv.DictReader(handle) if row.get("fc")}


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def compute_trend(history: list[dict]) -> Trend:
    """history: stored days for one FC, newest first (the first item is the digest day)."""
    if not history:
        return Trend()
    today = history[0]
    trend = Trend()
    if today["colour"] != Colour.GREEN.value:
        streak = 0
        for doc in history:
            if doc["colour"] != today["colour"]:
                break
            streak += 1
        trend.streak_colour, trend.streak_days = Colour(today["colour"]), streak
    last7 = history[:7]
    if len(last7) >= 2:
        trend.avg_cm2_7d = round(sum(d["cm2_pct"] for d in last7) / len(last7), 1)
    if len(history) >= 2:
        trend.prev_cm2 = history[1]["cm2_pct"]
    return trend


def build_digest(day_doc: dict, history: list[dict], manager: dict, insight_text: str,
                 insight_mode: str, dashboard_url: str) -> Digest:
    colour = day_doc["colour"]
    fg, bg = COLOURS[colour]
    day_label = date.fromisoformat(day_doc["date"]).strftime("%d %b %Y")
    trend = trend_sentence(compute_trend(history))
    open_items = [a for a in day_doc["anomalies"] if not a["acknowledged"]]
    contributors = sorted([a for a in open_items if a["status"] == "Above max"], key=lambda a: -a["impact_rupees"])
    contributors = contributors[:rules.TOP_CONTRIBUTORS_IN_DIGEST]
    known = len(day_doc["anomalies"]) - len(open_items)

    subject = f"[{colour.upper()}] {day_doc['fc']} P&L {day_label}: CM2 {day_doc['cm2_pct']:.1f}%"

    text_lines = [
        f"{day_doc['fc']} - daily P&L digest for {day_label}",
        f"Status: {colour}   CM2 {day_doc['cm2_pct']:.1f}%   CM1 {day_doc['cm1_pct']:.1f}%   Revenue {rupees(day_doc['revenue'])}",
        "", insight_text,
    ]
    if trend:
        text_lines += ["", trend]
    if known:
        text_lines += ["", f"{known} flag(s) marked as known issues are not repeated here."]
    text_lines += ["", f"Dashboard: {dashboard_url}"]

    rows = "".join(
        f"<tr><td style='padding:6px 10px;border-bottom:1px solid #eee'>{html.escape(a['line_item'])}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{a['pct_of_revenue']:.1f}%</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{html.escape(a['target_range'])}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{rupees(a['impact_rupees'])}</td></tr>"
        for a in contributors
    )
    table = (f"<table style='border-collapse:collapse;font-size:14px;margin:12px 0'>"
             f"<tr style='background:#f6f5f9'><th align='left' style='padding:6px 10px'>Cost line</th>"
             f"<th align='left' style='padding:6px 10px'>% of revenue</th><th align='left' style='padding:6px 10px'>Target</th>"
             f"<th align='left' style='padding:6px 10px'>Over by</th></tr>{rows}</table>") if contributors else ""
    greeting = f"Hi {html.escape(manager.get('manager') or 'team')},"

    body = f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:620px;color:#1f1f1f">
  <div style="background:{bg};color:{fg};border-left:6px solid {fg};padding:14px 18px;border-radius:6px">
    <div style="font-size:13px;letter-spacing:.04em;text-transform:uppercase">{html.escape(day_doc['fc'])} · {day_label}</div>
    <div style="font-size:22px;font-weight:bold;margin-top:4px">{colour}: CM2 {day_doc['cm2_pct']:.1f}%</div>
  </div>
  <p>{greeting}</p>
  <table style="font-size:14px;margin:6px 0 10px">
    <tr><td style="padding:2px 14px 2px 0;color:#666">Revenue</td><td><b>{rupees(day_doc['revenue'])}</b></td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#666">CM1</td><td><b>{day_doc['cm1_pct']:.1f}%</b> (target {rules.CM1_TARGET[0]:g}-{rules.CM1_TARGET[1]:g}%)</td></tr>
    <tr><td style="padding:2px 14px 2px 0;color:#666">CM2</td><td><b>{day_doc['cm2_pct']:.1f}%</b> (target {rules.CM2_TARGET[0]:g}-{rules.CM2_TARGET[1]:g}%)</td></tr>
  </table>
  <p style="font-size:15px;line-height:1.5">{html.escape(insight_text)}</p>
  {table}
  {f'<p style="color:#555;font-size:14px">{html.escape(trend)}</p>' if trend else ''}
  {f'<p style="color:#777;font-size:13px">{known} flag(s) marked as known issues are not repeated here.</p>' if known else ''}
  <p style="font-size:13px"><a href="{html.escape(dashboard_url)}">Open the FC dashboard</a></p>
  <p style="color:#999;font-size:12px">Automated digest · Prozo FC P&amp;L monitor</p>
</div>"""

    return Digest(fc=day_doc["fc"], day=day_doc["date"], colour=colour, subject=subject,
                  text="\n".join(text_lines), html=body, recipient=manager.get("email", ""),
                  manager=manager.get("manager", ""), insight_mode=insight_mode)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

class OutboxNotifier:
    channel = "outbox"

    def __init__(self, folder: Path):
        self.folder = folder

    def send(self, digest: Digest) -> Delivery:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{digest.day}_{digest.fc.replace(' ', '_')}.html"
        path.write_text(f"<!-- To: {digest.recipient or 'no recipient configured'} | Subject: {digest.subject} -->\n"
                        + digest.html, encoding="utf-8")
        return Delivery(self.channel, "saved", f"SMTP not configured - saved to {path.name}")


class EmailNotifier:
    channel = "email"

    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, digest: Digest) -> Delivery:
        if not digest.recipient:
            return Delivery(self.channel, "failed", f"No email address configured for {digest.fc}")
        message = EmailMessage()
        message["Subject"], message["From"], message["To"] = digest.subject, self.settings.smtp_from, digest.recipient
        message.set_content(digest.text)
        message.add_alternative(digest.html, subtype="html")
        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                if self.settings.smtp_user:
                    smtp.login(self.settings.smtp_user, self.settings.smtp_password)
                smtp.send_message(message)
            return Delivery(self.channel, "sent", f"Emailed to {digest.recipient}")
        except Exception as exc:  # network, auth, recipient refused ...
            log.warning("Digest email to %s failed: %s", digest.recipient, exc)
            return Delivery(self.channel, "failed", f"Email failed: {exc}")


def create_notifier(settings: Settings):
    return EmailNotifier(settings) if settings.smtp_configured else OutboxNotifier(settings.cs3_outbox_dir)
