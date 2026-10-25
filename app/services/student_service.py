from app.services.analytics_service import summarize_student_records


def student_attendance(records: list[dict], subject_ids: list[str]) -> dict:
    """Return the same class-weighted attendance totals used by student pages."""
    return summarize_student_records(records, subject_ids)


def absent_dates(records: list[dict]) -> list[dict]:
    return sorted((row for row in records if row.get("status") == "absent"), key=lambda row: row.get("date", ""), reverse=True)
