from typing import Any, Sequence

from app.domain.money import format_minor

# PRD section 09: every outbound message is built by a named builder. No ad hoc
# string building anywhere in the codebase; these are snapshot-tested.

# PRD section 16: a Slack message caps at five transactions so a channel post can
# never become a bulk export of the statement.
MAX_TRANSACTIONS_IN_MESSAGE = 5


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _button(text: str, action_id: str, value: str, style: str | None = None) -> dict[str, Any]:
    button: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": text},
        "action_id": action_id,
        "value": value,
    }
    if style:
        button["style"] = style
    return button


def build_run_summary(
    *,
    period: str,
    total_rows: int,
    matched: int,
    review: int,
    cases: int,
    value_at_risk_minor: int,
    confidence: int,
    currency: str = "NGN",
) -> dict[str, Any]:
    blocks = [
        _section(f"*{period} processing finished*"),
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Statement lines*\n{total_rows}"},
                {"type": "mrkdwn", "text": f"*Matched*\n{matched}"},
                {"type": "mrkdwn", "text": f"*Needs review*\n{review}"},
                {"type": "mrkdwn", "text": f"*Cases*\n{cases}"},
                {
                    "type": "mrkdwn",
                    "text": f"*Value at risk*\n{format_minor(value_at_risk_minor, currency)}",
                },
                {"type": "mrkdwn", "text": f"*Extraction confidence*\n{confidence}%"},
            ],
        },
        _context("Review outstanding items before closing the reconciliation."),
    ]
    return {
        "blocks": blocks,
        "text": f"{period}: {matched}/{total_rows} matched, {cases} cases open",
    }


def build_case_thread_opener(
    *,
    case_id: str,
    case_type: str,
    title: str,
    summary: str,
    priority: str,
    value_at_risk_minor: int,
    transactions: Sequence[str] = (),
    currency: str = "NGN",
) -> dict[str, Any]:
    shown = list(transactions[:MAX_TRANSACTIONS_IN_MESSAGE])
    remainder = len(transactions) - len(shown)

    blocks: list[dict[str, Any]] = [
        _section(f"*{title}*"),
        _context(
            f"{case_type} · {priority} · {format_minor(value_at_risk_minor, currency)} at risk"
        ),
        _section(summary),
    ]
    if shown:
        listing = "\n".join(f"• {line}" for line in shown)
        if remainder > 0:
            listing += f"\n_and {remainder} more, in the web app_"
        blocks.append(_section(listing))
    blocks.append(
        _context(
            "Status: *Pending*. Reply in this thread with what you know; when a reply settles it, "
            f"I will propose a resolution for one-click confirmation. Case `{case_id[:8]}`"
        )
    )
    return {"blocks": blocks, "text": title}


def build_listener_hit(
    *,
    case_id: str,
    evidence_id: str,
    author_slack_id: str,
    channel_name: str,
    relative_time: str,
    excerpt: str,
    matched_on: Sequence[str],
) -> dict[str, Any]:
    """PRD 6.5 step 4. The unverified-claim line is not decoration: it is the
    safety story and the innovation story in the same sentence."""
    blocks = [
        _section("*Possible match for this case.*"),
        _section(
            f"<@{author_slack_id}> in #{channel_name}, {relative_time}:\n>{excerpt}"
        ),
        _section(f"*Matched on:* {', '.join(matched_on)}"),
        _context(":warning: This is an unverified claim, not a ledger record."),
        {
            "type": "actions",
            "elements": [
                _button(
                    "Attach and propose closing",
                    "listener_attach",
                    f"{case_id}:{evidence_id}",
                    style="primary",
                ),
                _button("Not related", "listener_dismiss", f"{case_id}:{evidence_id}"),
            ],
        },
    ]
    return {"blocks": blocks, "text": "Possible match for this case"}


def build_approval_request(
    *,
    proposal_id: str,
    case_title: str,
    reason_code: str,
    narrative: str,
    value_at_risk_minor: int,
    evidence_count: int,
    requires_approver: bool,
    currency: str = "NGN",
) -> dict[str, Any]:
    blocks = [
        _section(f"*Proposed resolution:* {case_title}"),
        _context(
            f"{reason_code} · {format_minor(value_at_risk_minor, currency)} · "
            f"{evidence_count} piece(s) of evidence"
        ),
        _section(narrative),
    ]
    if requires_approver:
        blocks.append(
            _context(":lock: Above the approval threshold. An approver must apply this.")
        )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                _button("Approve", "proposal_approve", proposal_id, style="primary"),
                _button("Reject", "proposal_reject", proposal_id, style="danger"),
            ],
        }
    )
    return {"blocks": blocks, "text": f"Approval requested: {case_title}"}


def build_followup(
    *, case_id: str, case_title: str, assignee_slack_id: str | None, overdue_hours: int
) -> dict[str, Any]:
    who = f"<@{assignee_slack_id}>" if assignee_slack_id else "this case"
    blocks = [
        _section(f"{who} — *{case_title}* has been open {overdue_hours}h."),
        {
            "type": "actions",
            "elements": [
                _button("I am on it", "case_ack", case_id),
                _button("Escalate", "case_escalate", case_id),
            ],
        },
    ]
    return {"blocks": blocks, "text": f"Follow-up: {case_title}"}


def build_escalation(
    *, case_id: str, case_title: str, to_slack_id: str, reason: str
) -> dict[str, Any]:
    blocks = [
        _section(f"*Escalated to <@{to_slack_id}>:* {case_title}"),
        _section(reason),
        _context(f"Case {case_id}"),
    ]
    return {"blocks": blocks, "text": f"Escalated: {case_title}"}


def build_close_out(
    *, period: str, cases_closed: int, total_rows: int, matched: int
) -> dict[str, Any]:
    blocks = [
        _section(f"*{period} is closed.*"),
        _context(
            f"{matched}/{total_rows} lines matched · {cases_closed} case(s) resolved · "
            "full audit trail in the web app"
        ),
    ]
    return {"blocks": blocks, "text": f"{period} closed"}


def build_error(*, code: str, message: str, correlation_id: str = "") -> dict[str, Any]:
    """PRD rule F1: no error path leaves a thread without a next action or an owner."""
    blocks = [_section(message)]
    if correlation_id:
        blocks.append(_context(f"`{code}` · ref `{correlation_id}`"))
    else:
        blocks.append(_context(f"`{code}`"))
    return {"blocks": blocks, "text": message}


BUILDERS = {
    "build_run_summary": build_run_summary,
    "build_case_thread_opener": build_case_thread_opener,
    "build_listener_hit": build_listener_hit,
    "build_approval_request": build_approval_request,
    "build_followup": build_followup,
    "build_escalation": build_escalation,
    "build_close_out": build_close_out,
    "build_error": build_error,
}
