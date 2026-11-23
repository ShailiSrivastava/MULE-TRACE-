"""Bounded case report rendering and spreadsheet-safe CSV serialization."""

from __future__ import annotations

import csv
import html
import io
import json
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

CSV_COLUMNS = (
    "case_id",
    "dataset_id",
    "record_type",
    "account_id",
    "account_type",
    "institution_code",
    "country_code",
    "finding_id",
    "finding_category",
    "finding_severity",
    "finding_status",
    "finding_title",
    "transaction_id",
    "source_account_id",
    "target_account_id",
    "amount",
    "currency",
    "occurred_at",
    "transaction_type",
    "channel",
    "transaction_status",
    "evidence_role",
    "evidence_snapshot",
)


def _display(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    safe = html.escape(_display(value)).replace("\n", "<br/>")
    return Paragraph(safe, style)


def render_case_pdf(records: dict[str, Any]) -> bytes:
    """Render a bounded investigator report without exposing user email data."""

    case = records["case"]
    generated_at = datetime.now(UTC)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=f"Investigation case {case.id}",
        author="MuleTrace",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CaseSection",
            parent=styles["Heading2"],
            textColor=colors.HexColor("#16324F"),
            spaceBefore=10,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CaseBody",
            parent=styles["BodyText"],
            fontSize=8.5,
            leading=11,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="CaseSmall",
            parent=styles["BodyText"],
            fontSize=7,
            leading=9,
            wordWrap="CJK",
        )
    )
    title_style = ParagraphStyle(
        name="CaseTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=17,
    )
    story = [
        Paragraph("MuleTrace Investigation Report", title_style),
        Spacer(1, 8),
        _paragraph(case.title, styles["Heading1"]),
    ]
    creator = records.get("creator")
    assignee = records.get("assignee")
    overview = [
        ["Case ID", str(case.id), "Dataset ID", str(case.dataset_id)],
        ["Status", case.status, "Priority", case.priority],
        ["Category", case.category, "Created", _display(case.opened_at)],
        [
            "Created by",
            _display(creator.display_name if creator else None),
            "Assigned to",
            _display(assignee.display_name if assignee else None),
        ],
        [
            "Closed",
            _display(case.closed_at),
            "Report generated",
            generated_at.isoformat(),
        ],
    ]
    story.append(
        Table(
            overview,
            colWidths=[0.9 * inch, 2.55 * inch, 0.95 * inch, 2.55 * inch],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8EEF4")),
                    ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#E8EEF4")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#AAB7C4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        )
    )
    story.extend(
        [
            Paragraph("Case description", styles["CaseSection"]),
            _paragraph(
                case.description or "No description provided.", styles["CaseBody"]
            ),
            Paragraph("Associated accounts", styles["CaseSection"]),
        ]
    )
    account_data = [["Account ID", "Type", "Institution", "Country", "Snapshot"]]
    for link, account in records["accounts"]:
        snapshot = link.evidence_snapshot or {}
        account_data.append(
            [
                _paragraph(account.id, styles["CaseSmall"]),
                _paragraph(
                    snapshot.get("account_type", account.account_type),
                    styles["CaseSmall"],
                ),
                _paragraph(
                    snapshot.get("institution_code", account.institution_code),
                    styles["CaseSmall"],
                ),
                _paragraph(
                    snapshot.get("country_code", account.country_code),
                    styles["CaseSmall"],
                ),
                _paragraph(snapshot.get("observed_at"), styles["CaseSmall"]),
            ]
        )
    if len(account_data) == 1:
        account_data.append(["No associated accounts", "", "", "", ""])
    story.append(
        Table(
            account_data,
            repeatRows=1,
            colWidths=[1.55 * inch, 0.75 * inch, 1.1 * inch, 0.55 * inch, 2.1 * inch],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D8E5F0")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B5C1CB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                ]
            ),
        )
    )
    story.append(Paragraph("Associated findings and evidence", styles["CaseSection"]))
    if not records["findings"]:
        story.append(_paragraph("No findings linked to this case.", styles["CaseBody"]))
    for link, finding in records["findings"]:
        story.extend(
            [
                _paragraph(
                    f"{finding.title} ({finding.severity}; {finding.status})",
                    styles["Heading3"],
                ),
                _paragraph(
                    f"Finding ID: {finding.id} | Category: {finding.category}",
                    styles["CaseSmall"],
                ),
                _paragraph(finding.explanation, styles["CaseBody"]),
                _paragraph(
                    "Evidence snapshot: "
                    + json.dumps(
                        link.evidence_snapshot or {}, sort_keys=True, default=str
                    ),
                    styles["CaseSmall"],
                ),
            ]
        )
    story.append(Paragraph("Investigation notes", styles["CaseSection"]))
    if not records["notes"]:
        story.append(_paragraph("No notes recorded.", styles["CaseBody"]))
    for note, author in records["notes"]:
        note_state = " (archived)" if note.archived_at is not None else ""
        story.extend(
            [
                _paragraph(
                    f"{author.display_name if author else 'Former user'} — "
                    f"{_display(note.created_at)}{note_state}",
                    styles["CaseSmall"],
                ),
                _paragraph(note.content, styles["CaseBody"]),
                Spacer(1, 4),
            ]
        )
    story.append(Paragraph("Investigation timeline", styles["CaseSection"]))
    timeline_data = [["Timestamp (UTC)", "Event", "Actor", "Safe metadata"]]
    for event, event_actor in records["timeline"]:
        safe_metadata = {
            key: value
            for key, value in (event.details or {}).items()
            if key
            in {
                "fields",
                "from_status",
                "to_status",
                "previous_assignee_id",
                "assigned_to_id",
                "account_id",
                "finding_id",
                "note_id",
                "revision_number",
                "archived",
                "dataset_id",
            }
        }
        timeline_data.append(
            [
                _paragraph(event.created_at, styles["CaseSmall"]),
                _paragraph(event.event_type, styles["CaseSmall"]),
                _paragraph(
                    event_actor.display_name if event_actor else "Former user",
                    styles["CaseSmall"],
                ),
                _paragraph(
                    json.dumps(safe_metadata, sort_keys=True), styles["CaseSmall"]
                ),
            ]
        )
    if len(timeline_data) == 1:
        timeline_data.append(["No events", "", "", ""])
    story.append(
        Table(
            timeline_data,
            repeatRows=1,
            colWidths=[1.35 * inch, 1.25 * inch, 1.15 * inch, 2.9 * inch],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D8E5F0")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B5C1CB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                ]
            ),
        )
    )

    def add_page_number(canvas, _document) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#667788"))
        canvas.drawRightString(
            letter[0] - 0.55 * inch, 0.3 * inch, f"Page {_document.page}"
        )
        canvas.restoreState()

    document.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buffer.getvalue()


def render_case_csv(
    *, case_id: str, dataset_id: str, evidence_rows: list[dict[str, Any]]
) -> str:
    """Write a bounded CSV and neutralize formula-triggering text cells."""

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for evidence in evidence_rows:
        row = {
            "case_id": case_id,
            "dataset_id": dataset_id,
            **evidence,
        }
        if isinstance(row.get("evidence_snapshot"), dict):
            row["evidence_snapshot"] = json.dumps(
                row["evidence_snapshot"],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        for key, value in row.items():
            if isinstance(value, str) and value.lstrip().startswith(
                ("=", "+", "-", "@")
            ):
                row[key] = "'" + value
        writer.writerow(row)
    return buffer.getvalue()
