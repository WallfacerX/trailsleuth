"""Deterministic investigation signals, not verdicts of compromise."""

from collections.abc import Iterable
from dataclasses import dataclass

from trailsleuth.normalization import NormalizedEvent


@dataclass(frozen=True)
class Finding:
    rule_id: str
    event_id: str
    severity: str
    reason: str
    source_reference: str


RULES = {
    ("cloudtrail.amazonaws.com", "StopLogging"): (
        "TS-001",
        "high",
        "CloudTrail logging was stopped; investigate the actor and affected trail.",
    ),
    ("iam.amazonaws.com", "CreateAccessKey"): (
        "TS-002",
        "medium",
        "A new access key was created; investigate the actor and intended use.",
    ),
}


def detect(events: Iterable[NormalizedEvent]) -> list[Finding]:
    """Match successful actions in input order; any populated error suppresses a match."""
    findings = []
    for event in events:
        rule = RULES.get((event.source, event.action))
        if rule is None or event.error_code or event.error_message:
            continue
        rule_id, severity, reason = rule
        findings.append(
            Finding(
                rule_id=rule_id,
                event_id=event.event_id,
                severity=severity,
                reason=f"{reason} This can be legitimate administration and alone does not "
                "prove compromise.",
                source_reference=event.source_reference,
            )
        )
    return findings
