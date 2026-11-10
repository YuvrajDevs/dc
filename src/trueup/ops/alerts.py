"""Alerts: always written to the ledger and the log; optionally posted to a webhook.

Raising an alert must never break the pipeline, so every sink fails quietly.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid

from trueup.ops.ledger import Ledger

log = logging.getLogger("trueup.alerts")
SEVERITIES = ("info", "warning", "critical")


class Alerter:
    def __init__(self, ledger: Ledger, webhook: str | None = None):
        self.ledger = ledger
        self.webhook = webhook if webhook is not None else os.environ.get("TRUEUP_ALERT_WEBHOOK")

    def raise_alert(
        self, severity: str, kind: str, message: str, run_id: str | None = None
    ) -> None:
        assert severity in SEVERITIES, severity
        try:
            self.ledger._run(
                "INSERT INTO ops.alerts VALUES (?, now(), ?, ?, ?, ?)",
                [uuid.uuid4().hex[:12], severity, kind, run_id, message],
            )
        except Exception:  # never let alerting break the run
            log.exception("could not record alert %s", kind)
        log.log(
            logging.ERROR if severity == "critical" else logging.WARNING,
            "[%s] %s: %s",
            severity,
            kind,
            message,
        )
        if self.webhook:
            try:
                body = json.dumps(
                    {"severity": severity, "kind": kind, "run_id": run_id, "message": message}
                )
                req = urllib.request.Request(
                    self.webhook, data=body.encode(), headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(req, timeout=5)  # noqa: S310
            except Exception:
                log.warning("webhook delivery failed for %s", kind)
