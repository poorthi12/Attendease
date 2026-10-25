"""Insert an eight-subject-per-semester B.Tech CSE starter catalog into MongoDB.

Safe to run repeatedly: matching records are kept, missing records are inserted,
and conflicting records cause the script to stop without changing the catalog.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys

from bson import ObjectId

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import ensure_indexes, get_database


DEPARTMENT = "Computer Science and Engineering"
ACADEMIC_YEAR = "2026-27"

# General B.Tech CSE starter curriculum. Institutions can replace these with
# their own approved syllabus and subject codes in the administrator catalog.
SEMESTER_SUBJECTS = {
    "Semester 1": [
        ("CSE101", "Engineering Mathematics I"),
        ("CSE102", "Engineering Physics"),
        ("CSE103", "Engineering Chemistry"),
        ("CSE104", "Programming for Problem Solving"),
        ("CSE105", "Basic Electrical and Electronics Engineering"),
        ("CSE106", "Engineering Graphics and Design"),
        ("CSE107", "Communication Skills"),
        ("CSE108", "Environmental Studies"),
    ],
    "Semester 2": [
        ("CSE201", "Engineering Mathematics II"),
        ("CSE202", "Data Structures"),
        ("CSE203", "Object Oriented Programming"),
        ("CSE204", "Digital Logic Design"),
        ("CSE205", "Discrete Mathematics"),
        ("CSE206", "Computer Organization Fundamentals"),
        ("CSE207", "Engineering Workshop"),
        ("CSE208", "Technical Communication"),
    ],
    "Semester 3": [
        ("CSE301", "Engineering Mathematics III"),
        ("CSE302", "Data Structures and Algorithms"),
        ("CSE303", "Object Oriented Programming with Java"),
        ("CSE304", "Digital Logic and Computer Organization"),
        ("CSE305", "Database Management Systems"),
        ("CSE306", "Operating Systems"),
        ("CSE307", "Probability and Statistics for Computing"),
        ("CSE308", "Data Structures Laboratory"),
    ],
    "Semester 4": [
        ("CSE401", "Design and Analysis of Algorithms"),
        ("CSE402", "Computer Networks"),
        ("CSE403", "Theory of Computation"),
        ("CSE404", "Microprocessors and Microcontrollers"),
        ("CSE405", "Software Engineering"),
        ("CSE406", "Database Systems Laboratory"),
        ("CSE407", "Operating Systems Laboratory"),
        ("CSE408", "Professional Communication"),
    ],
    "Semester 5": [
        ("CSE501", "Compiler Design"),
        ("CSE502", "Web Technologies"),
        ("CSE503", "Computer Graphics"),
        ("CSE504", "Information and Cyber Security"),
        ("CSE505", "Distributed Systems"),
        ("CSE506", "Web Technologies Laboratory"),
        ("CSE507", "Software Testing and Quality Assurance"),
        ("CSE508", "Mini Project I"),
    ],
    "Semester 6": [
        ("CSE601", "Artificial Intelligence"),
        ("CSE602", "Machine Learning"),
        ("CSE603", "Cloud Computing"),
        ("CSE604", "Data Warehousing and Data Mining"),
        ("CSE605", "Mobile Application Development"),
        ("CSE606", "Machine Learning Laboratory"),
        ("CSE607", "Internet of Things"),
        ("CSE608", "Project Phase I"),
    ],
    "Semester 7": [
        ("CSE701", "Big Data Analytics"),
        ("CSE702", "Deep Learning"),
        ("CSE703", "DevOps and Site Reliability Engineering"),
        ("CSE704", "Blockchain Technology"),
        ("CSE705", "Natural Language Processing"),
        ("CSE706", "Software Architecture and Design Patterns"),
        ("CSE707", "Technical Seminar"),
        ("CSE708", "Industry Internship"),
    ],
    "Semester 8": [
        ("CSE801", "Computer Vision"),
        ("CSE802", "Information Retrieval"),
        ("CSE803", "Edge and Fog Computing"),
        ("CSE804", "Advanced Database Systems"),
        ("CSE805", "Entrepreneurship and Innovation"),
        ("CSE806", "Professional Elective"),
        ("CSE807", "Project Phase II"),
        ("CSE808", "Technical Viva and Project Presentation"),
    ],
}


def build_documents() -> list[dict]:
    documents = []
    for semester, subjects in SEMESTER_SUBJECTS.items():
        if len(subjects) != 8:
            raise ValueError(f"{semester} must have exactly eight subjects")
        for code, name in subjects:
            documents.append(
                {
                    "_id": ObjectId(),
                    "code": code,
                    "name": name,
                    "department": DEPARTMENT,
                    "academic_year": ACADEMIC_YEAR,
                    "semester": semester,
                    "active": True,
                    "created_at": datetime.now(timezone.utc),
                }
            )
    if len(documents) != 64:
        raise ValueError("The B.Tech CSE catalog must contain exactly 64 subjects")
    return documents


def seed_catalog() -> tuple[int, int]:
    database = get_database()
    ensure_indexes(database)
    desired = build_documents()
    by_code = {document["code"]: document for document in desired}

    # Do all conflict checks before writing anything. This prevents the seed
    # from overwriting an institution's existing subject or breaking an 8-item group.
    for document in desired:
        existing = database.subjects.find_one({"code": document["code"]})
        if existing is not None and any(
            existing.get(field) != document[field]
            for field in ("name", "department", "academic_year", "semester", "active")
        ):
            raise ValueError(f"Subject code {document['code']} already belongs to a different catalog entry")

    for semester in SEMESTER_SUBJECTS:
        active = list(
            database.subjects.find(
                {
                    "department": DEPARTMENT,
                    "academic_year": ACADEMIC_YEAR,
                    "semester": semester,
                    "active": {"$ne": False},
                }
            )
        )
        unexpected = [row.get("code", "(no code)") for row in active if row.get("code") not in by_code]
        if unexpected:
            raise ValueError(
                f"{semester} already contains other active subjects: {', '.join(unexpected)}"
            )

    existing_codes = {
        row["code"]
        for row in database.subjects.find({"code": {"$in": list(by_code)}})
    }
    missing = [document for document in desired if document["code"] not in existing_codes]
    if missing:
        database.subjects.insert_many(missing, ordered=True)
    return len(missing), len(existing_codes)


if __name__ == "__main__":
    inserted, already_present = seed_catalog()
    print(
        f"B.Tech CSE catalog ready: {inserted} subjects inserted, "
        f"{already_present} already present, 8 semesters × 8 subjects."
    )
