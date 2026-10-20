"""One-off: verify the alert email pipeline (Resend + sender domain + recipients).
Sends a clearly-labeled TEST message to each configured alert recipient and
prints the per-recipient send status. Does NOT trigger a fake GPU alert."""
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()  # same .env the app uses

from api import emailer  # noqa: E402

recipients = [r.strip() for r in os.environ.get(
    "AKARI_GPU_ALERT_TO", "").split(",") if r.strip()]

print("is_configured (enabled + key present):", emailer.is_configured())
print("sender:", os.environ.get("AKARI_EMAIL_FROM"))
print("recipients:", recipients)

ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
subject = "[AKARI TEST] monitoring email check - no action needed"
text = (
    "This is a TEST of the AKARI reliability alert email pipeline.\n\n"
    f"Sent: {ts}\n\n"
    "If you received this, the GPU power-cap watcher and the system-down "
    "watchdog can reach your inbox. No outage is occurring. No action needed.\n\n"
    "- AKARI monitoring"
)
html = f"<pre style='font-family:Segoe UI,Arial,sans-serif;white-space:pre-wrap'>{text}</pre>"

for to in recipients:
    res = emailer.send(to, subject, html, text)
    print(f"  -> {to}: {res.get('status')}  {res.get('provider_id') or res.get('error') or ''}")
