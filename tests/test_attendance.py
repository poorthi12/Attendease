from datetime import date, datetime, timedelta, timezone

import pytest
from bson import ObjectId

from app.services.attendance_service import attendance_percentage, attendance_summary, finalize_attendance
from app.services.student_service import absent_dates


def test_attendance_percentages_and_weighted_summary():
    assert attendance_percentage(16, 20) == 80.0
    assert attendance_percentage(0, 0) is None
    summary = attendance_summary([
        {"applicable_sessions": 2, "present_count": 2},
        {"applicable_sessions": 18, "present_count": 14},
    ])
    assert summary == {"classes": 20, "present": 16, "absent": 4, "percentage": 80.0}


@pytest.mark.parametrize("present,total", [(-1, 2), (3, 2), (1, -1)])
def test_inconsistent_counts_are_rejected(present, total):
    with pytest.raises(ValueError):
        attendance_percentage(present, total)


def test_absent_dates_are_sorted_newest_first():
    rows = [{"date": "2026-01-01", "status": "absent"}, {"date": "2026-02-01", "status": "present"}, {"date": "2026-01-14", "status": "absent"}]
    assert [row["date"] for row in absent_dates(rows)] == ["2026-01-14", "2026-01-01"]


def test_attendance_finalization_is_complete_and_duplicate_safe(database):
    subject_id, teacher_id = ObjectId(), ObjectId()
    student_ids = {str(ObjectId()), str(ObjectId())}
    session_id = finalize_attendance(database, subject_id=subject_id, teacher_id=teacher_id, class_date=date(2026, 1, 2), statuses={student: "present" for student in student_ids}, enrolled_student_ids=student_ids)
    assert database.attendance_sessions.count_documents({"_id": session_id, "status": "finalized"}) == 1
    assert database.attendance_records.count_documents({"session_id": session_id}) == 2
    assert database.audit_logs.count_documents({"target_id": session_id, "action": "attendance.finalized"}) == 1
    with pytest.raises(ValueError, match="already been recorded"):
        finalize_attendance(database, subject_id=subject_id, teacher_id=teacher_id, class_date=date(2026, 1, 2), statuses={student: "present" for student in student_ids}, enrolled_student_ids=student_ids)
    assert database.attendance_sessions.count_documents({"subject_id": subject_id}) == 1
    assert database.attendance_records.count_documents({"subject_id": subject_id}) == 2


def test_attendance_rejects_roster_mismatch(database):
    with pytest.raises(ValueError, match="every currently enrolled"):
        finalize_attendance(database, subject_id=ObjectId(), teacher_id=ObjectId(), class_date=date(2026, 1, 2), statuses={}, enrolled_student_ids={str(ObjectId())})


def test_stale_finalizing_session_is_cleaned_before_retry(database):
    subject_id, teacher_id, student_id, old_session_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    class_date = date(2026, 1, 2)
    database.attendance_sessions.insert_one({"_id": old_session_id, "subject_id": subject_id, "date": class_date.isoformat(), "status": "finalizing", "created_at": datetime.now(timezone.utc) - timedelta(minutes=16)})
    database.attendance_records.insert_one({"session_id": old_session_id, "subject_id": subject_id, "student_id": student_id, "date": class_date.isoformat(), "status": "present"})
    database.audit_logs.insert_one({"target_id": old_session_id, "action": "attendance.finalized"})
    result = finalize_attendance(database, subject_id=subject_id, teacher_id=teacher_id, class_date=class_date, statuses={str(student_id): "absent"}, enrolled_student_ids={str(student_id)})
    assert result != old_session_id
    assert database.attendance_sessions.count_documents({"subject_id": subject_id, "status": "finalized"}) == 1
    assert database.attendance_records.count_documents({"session_id": old_session_id}) == 0
    assert database.attendance_records.count_documents({"session_id": result}) == 1
