"""Engine entry point for the Telegram approval gateway (ENGINE-PLAN step 2).

Runs the canonical implementation at approvals/telegram_approvals.py with identical
CLI, including --tenant / TENANT_CONFIG. The real code stays there for now because
the scheduled tasks and RUNBOOK call that path; the direction flips when the client
package is cut (step 6).

  python engine/gateway/telegram_gateway.py <command> [...] [--tenant tenants/<x>/config.json]
"""
import runpy
import sys
from pathlib import Path

sys.argv[0] = str(Path(__file__).resolve().parents[2] / "approvals" / "telegram_approvals.py")
runpy.run_path(sys.argv[0], run_name="__main__")
