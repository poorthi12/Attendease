from collections import defaultdict
from typing import Iterable

from app.services.attendance_service import attendance_percentage, attendance_summary


def summarize_student_records(records: Iterable[dict], enrolled_subject_ids: Iterable[str]) -> dict:
    subjects = {str(subject_id): {"classes": 0, "present": 0, "records": []} for subject_id in enrolled_subject_ids}
    for record in records:
        subject_id = str(record.get("subject_id", ""))
        if subject_id not in subjects:
            continue
        item = subjects[subject_id]
        item["classes"] += 1
        item["present"] += int(record.get("status") == "present")
        item["records"].append(record)
    for item in subjects.values():
        item["absent"] = item["classes"] - item["present"]
        item["percentage"] = attendance_percentage(item["present"], item["classes"])
    overall = attendance_summary(
        {"applicable_sessions": item["classes"], "present_count": item["present"]}
        for item in subjects.values()
    )
    return {"subjects": subjects, "overall": overall}


def summarize_teacher_records(records: Iterable[dict]) -> dict:
    present = absent = 0
    by_date: dict[str, dict[str, int]] = defaultdict(lambda: {"present": 0, "absent": 0})
    by_subject: dict[str, dict[str, int]] = defaultdict(lambda: {"present": 0, "absent": 0})
    for record in records:
        status = record.get("status")
        if status not in {"present", "absent"}:
            continue
        if status == "present":
            present += 1
        else:
            absent += 1
        by_date[str(record.get("date", ""))][status] += 1
        by_subject[str(record.get("subject_id", ""))][status] += 1
    return {
        "present": present,
        "absent": absent,
        "records": present + absent,
        "by_date": dict(sorted(by_date.items())),
        "by_subject": dict(by_subject),
    }
