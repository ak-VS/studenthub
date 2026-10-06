"""Creates tables, the first admin, and (with --demo) sample data.

Usage:
    python init_db.py          # tables + admin
    python init_db.py --demo   # also adds sample courses, teacher, students, marks
"""
import os
import random
import sys
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from database import get_db_connection


def hash_pw(p):
    return generate_password_hash(p, method="pbkdf2:sha256")


def main():
    demo = "--demo" in sys.argv
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        for stmt in f.read().split(";"):
            if stmt.strip():
                cur.execute(stmt)

    admin_email = os.environ.get("ADMIN_EMAIL", "admin@studenthub.com").lower()
    admin_pw = os.environ.get("ADMIN_PASSWORD", "admin123")
    cur.execute("SELECT id FROM users WHERE email=%s", (admin_email,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (name,email,password_hash,role,must_change_password) "
            "VALUES ('Admin',%s,%s,'admin',1)",
            (admin_email, hash_pw(admin_pw)),
        )
        print(f"Admin created: {admin_email} / {admin_pw} (must change on first login)")

    if demo:
        cur.execute("SELECT COUNT(*) AS n FROM courses")
        if cur.fetchone()["n"] == 0:
            for c in ("BCA", "BSc Computer Science", "MBA"):
                cur.execute("INSERT INTO courses (name) VALUES (%s)", (c,))

        cur.execute("SELECT id FROM courses ORDER BY id LIMIT 1")
        course_id = cur.fetchone()["id"]

        cur.execute("SELECT id FROM users WHERE email='teacher@studenthub.com'")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO users (name,email,password_hash,role,must_change_password) "
                "VALUES ('Demo Teacher','teacher@studenthub.com',%s,'teacher',0)",
                (hash_pw("teacher123"),),
            )
            teacher_id = cur.lastrowid
            subject_ids = []
            for s in ("Python Programming", "Database Systems", "Mathematics"):
                cur.execute(
                    "INSERT INTO subjects (name,course_id,teacher_id) VALUES (%s,%s,%s)",
                    (s, course_id, teacher_id),
                )
                subject_ids.append(cur.lastrowid)

            people = [
                ("Aarav Mehta", "aarav@example.com", date(2003, 5, 14)),
                ("Diya Sharma", "diya@example.com", date(2003, 11, 2)),
                ("Rohan Verma", "rohan@example.com", date(2002, 8, 21)),
            ]
            random.seed(1)
            for name, email, dob in people:
                cur.execute(
                    "INSERT INTO students (name,email,gender,course_id,date_of_birth,status) "
                    "VALUES (%s,%s,'',%s,%s,'Active')",
                    (name, email, course_id, dob),
                )
                sid = cur.lastrowid
                cur.execute(
                    "INSERT INTO users (name,email,password_hash,role,student_id,must_change_password) "
                    "VALUES (%s,%s,%s,'student',%s,0)",
                    (name, email, hash_pw(dob.strftime("%d%m%Y")), sid),
                )
                for sub in subject_ids:
                    for exam, mx in (("Quiz 1", 20), ("Midterm", 50)):
                        cur.execute(
                            "INSERT INTO marks (student_id,subject_id,exam_type,marks_obtained,max_marks) "
                            "VALUES (%s,%s,%s,%s,%s)",
                            (sid, sub, exam, random.randint(int(mx * 0.5), mx), mx),
                        )
                    for d in range(10):
                        day = date.today() - timedelta(days=d + 1)
                        cur.execute(
                            "INSERT INTO attendance (student_id,subject_id,att_date,status) "
                            "VALUES (%s,%s,%s,%s)",
                            (sid, sub, day, "Present" if random.random() < 0.8 else "Absent"),
                        )
            print("Demo data added.")
            print("  teacher@studenthub.com / teacher123")
            print("  aarav@example.com / 14052003 (DOB as DDMMYYYY)")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
