import csv
import io
import os
from collections import defaultdict
from datetime import date, datetime
from functools import wraps

import mysql.connector
from flask import (
    Flask, Response, abort, flash, g, jsonify, redirect,
    render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db_connection

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

LOW_ATTENDANCE = 75
LOW_MARKS = 40  # pass mark (%) and at-risk threshold
HOME = {
    "admin": "admin_dashboard",
    "teacher": "teacher_dashboard",
    "student": "student_dashboard",
}


# ---------------------------------------------------------------- helpers

def get_conn():
    """One database connection per request (opening SSL connections is slow)."""
    conn = g.get("db")
    if conn is None or not conn.is_connected():
        conn = g.db = get_db_connection()
    return conn


@app.teardown_appcontext
def close_conn(exc):
    conn = g.pop("db", None)
    if conn is not None:
        try:
            conn.close()
        except mysql.connector.Error:
            pass


def q(sql, params=(), one=False):
    """Run a SELECT and return dict rows (or one row)."""
    cur = get_conn().cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        cur.close()


def run(sql, params=()):
    """Run a single INSERT/UPDATE/DELETE and return lastrowid."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    except mysql.connector.Error:
        conn.rollback()
        raise
    finally:
        cur.close()


def hash_pw(password):
    return generate_password_hash(password, method="pbkdf2:sha256")


def dob_password(dob):
    """Default student password: date of birth as DDMMYYYY."""
    if isinstance(dob, str):
        dob = datetime.strptime(dob, "%Y-%m-%d")
    return dob.strftime("%d%m%Y")


def pct(part, whole):
    if not whole:
        return None
    return round(100 * float(part) / float(whole), 1)


def grade_for(percent):
    if percent is None:
        return "-"
    for cutoff, letter in ((90, "A+"), (80, "A"), (70, "B+"), (60, "B"), (50, "C"), (40, "D")):
        if percent >= cutoff:
            return letter
    return "F"


# ------------------------------------------------------------------- auth

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.before_request
def force_password_change():
    if session.get("must_change") and request.endpoint not in (
        "change_password", "logout", "static"
    ):
        return redirect(url_for("change_password"))


@app.errorhandler(403)
def forbidden(e):
    return render_template(
        "error.html", code=403,
        message="You don't have permission to open this page."
    ), 403


@app.errorhandler(404)
def not_found(e):
    return render_template(
        "error.html", code=404, message="That page doesn't exist."
    ), 404


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = q("SELECT * FROM users WHERE email = %s", (email,), one=True)

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            session["student_id"] = user["student_id"]
            session["must_change"] = bool(user["must_change_password"])
            if session["must_change"]:
                flash("Please set a new password to continue.", "success")
                return redirect(url_for("change_password"))
            return redirect(url_for("home"))

        flash("Incorrect email or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")

        user = q("SELECT * FROM users WHERE id = %s", (session["user_id"],), one=True)

        if not check_password_hash(user["password_hash"], current):
            flash("Current password is incorrect.", "error")
        elif len(new) < 6:
            flash("New password must be at least 6 characters.", "error")
        elif new != confirm:
            flash("New passwords do not match.", "error")
        elif new == current:
            flash("New password must be different from the current one.", "error")
        else:
            run(
                "UPDATE users SET password_hash=%s, must_change_password=0 WHERE id=%s",
                (hash_pw(new), user["id"]),
            )
            session["must_change"] = False
            flash("Password updated.", "success")
            return redirect(url_for("home"))

    return render_template("change_password.html")


@app.route("/")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return redirect(url_for(HOME[session["role"]]))


# ------------------------------------------------------------------ admin

@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    counts = q(
        """
        SELECT
            (SELECT COUNT(*) FROM students) AS total_students,
            (SELECT COUNT(*) FROM students WHERE status = 'Active') AS active_students,
            (SELECT COUNT(*) FROM courses) AS total_courses,
            (SELECT COUNT(*) FROM users WHERE role = 'teacher') AS total_teachers,
            (SELECT COUNT(*) FROM subjects) AS total_subjects
        """,
        one=True,
    )
    total_students = counts["total_students"]
    active_students = counts["active_students"]
    total_courses = counts["total_courses"]
    total_teachers = counts["total_teachers"]
    total_subjects = counts["total_subjects"]

    recent_students = q(
        """
        SELECT students.id, students.name, courses.name AS course, students.status
        FROM students
        INNER JOIN courses ON students.course_id = courses.id
        ORDER BY students.id DESC LIMIT 5
        """
    )
    course_stats = q(
        """
        SELECT courses.name AS course, COUNT(students.id) AS total
        FROM courses
        LEFT JOIN students ON courses.id = students.course_id
        GROUP BY courses.id, courses.name
        ORDER BY total DESC
        """
    )
    return render_template(
        "admin_dashboard.html",
        total_students=total_students,
        active_students=active_students,
        inactive_students=total_students - active_students,
        total_courses=total_courses,
        total_teachers=total_teachers,
        total_subjects=total_subjects,
        recent_students=recent_students,
        course_stats=course_stats,
        at_risk_count=len(at_risk_rows()),
        pending_leaves=pending_leave_count(),
    )


@app.route("/students")
@role_required("admin")
def students():
    search = request.args.get("search", "").strip()
    course_id = request.args.get("course_id", "")
    status = request.args.get("status", "")
    sort = request.args.get("sort", "")

    query = """
        SELECT students.id, students.name, students.email, students.phone,
               students.gender, students.address, students.status,
               courses.name AS course
        FROM students
        INNER JOIN courses ON students.course_id = courses.id
        WHERE 1 = 1
    """
    params = []

    if search:
        query += " AND (students.name LIKE %s OR students.email LIKE %s OR students.phone LIKE %s)"
        params += [f"%{search}%"] * 3
    if course_id:
        query += " AND students.course_id = %s"
        params.append(course_id)
    if status:
        query += " AND students.status = %s"
        params.append(status)

    if sort == "az":
        query += " ORDER BY students.name ASC"
    elif sort == "za":
        query += " ORDER BY students.name DESC"
    else:
        query += " ORDER BY students.id DESC"

    return render_template(
        "students.html",
        students=q(query, tuple(params)),
        courses=q("SELECT id, name FROM courses ORDER BY name"),
        search=search,
        selected_course=course_id,
        selected_status=status,
        selected_sort=sort,
    )


FORM_FIELDS = (
    "name", "email", "phone", "gender", "course_id",
    "date_of_birth", "status", "address",
)


@app.route("/student/add", methods=["GET", "POST"])
@role_required("admin")
def add_student():
    courses = q("SELECT id, name FROM courses ORDER BY name")

    if request.method == "POST":
        f = {k: request.form.get(k, "").strip() for k in FORM_FIELDS}
        f["email"] = f["email"].lower()

        if not (f["name"] and f["email"] and f["course_id"] and f["date_of_birth"]):
            flash("Name, email, course and date of birth are required.", "error")
            return render_template(
                "student_form.html", student=f, courses=courses, form_title="Add Student"
            )

        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO students
                (name, email, phone, gender, course_id, date_of_birth, status, address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (f["name"], f["email"], f["phone"], f["gender"], f["course_id"],
                 f["date_of_birth"], f["status"] or "Active", f["address"]),
            )
            student_id = cur.lastrowid
            cur.execute(
                """
                INSERT INTO users
                (name, email, password_hash, role, student_id, must_change_password)
                VALUES (%s, %s, %s, 'student', %s, 1)
                """,
                (f["name"], f["email"], hash_pw(dob_password(f["date_of_birth"])), student_id),
            )
            conn.commit()
        except mysql.connector.Error:
            conn.rollback()
            flash("Could not add student. That email may already be in use.", "error")
            return render_template(
                "student_form.html", student=f, courses=courses, form_title="Add Student"
            )
        finally:
            conn.close()

        flash(
            f"Student added. Login: {f['email']} | temporary password: date of birth as DDMMYYYY.",
            "success",
        )
        return redirect(url_for("students"))

    return render_template(
        "student_form.html", student=None, courses=courses, form_title="Add Student"
    )


@app.route("/student/<int:student_id>")
@role_required("admin")
def student_detail(student_id):
    student = q(
        """
        SELECT students.*, courses.name AS course
        FROM students
        INNER JOIN courses ON students.course_id = courses.id
        WHERE students.id = %s
        """,
        (student_id,), one=True,
    )
    if student is None:
        flash("Student not found.", "error")
        return redirect(url_for("students"))

    login_user = q(
        "SELECT id, must_change_password FROM users WHERE student_id = %s",
        (student_id,), one=True,
    )
    return render_template("student_details.html", student=student, login_user=login_user)


@app.route("/student/edit/<int:student_id>", methods=["GET", "POST"])
@role_required("admin")
def edit_student(student_id):
    student = q("SELECT * FROM students WHERE id = %s", (student_id,), one=True)
    if student is None:
        flash("Student not found.", "error")
        return redirect(url_for("students"))

    courses = q("SELECT id, name FROM courses ORDER BY name")

    if request.method == "POST":
        f = {k: request.form.get(k, "").strip() for k in FORM_FIELDS}
        f["email"] = f["email"].lower()

        if not (f["name"] and f["email"] and f["course_id"]):
            flash("Name, email and course are required.", "error")
            return render_template(
                "student_form.html", student={**f, "id": student_id},
                courses=courses, form_title="Edit Student",
            )

        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE students
                SET name=%s, email=%s, phone=%s, gender=%s, course_id=%s,
                    date_of_birth=%s, address=%s, status=%s
                WHERE id=%s
                """,
                (f["name"], f["email"], f["phone"], f["gender"], f["course_id"],
                 f["date_of_birth"] or None, f["address"], f["status"], student_id),
            )
            cur.execute(
                "UPDATE users SET name=%s, email=%s WHERE student_id=%s",
                (f["name"], f["email"], student_id),
            )
            conn.commit()
        except mysql.connector.Error:
            conn.rollback()
            flash("Could not update student. That email may already be in use.", "error")
            return render_template(
                "student_form.html", student={**f, "id": student_id},
                courses=courses, form_title="Edit Student",
            )
        finally:
            conn.close()

        flash("Student updated.", "success")
        return redirect(url_for("student_detail", student_id=student_id))

    return render_template(
        "student_form.html", student=student, courses=courses, form_title="Edit Student"
    )


@app.route("/student/delete/<int:student_id>", methods=["POST"])
@role_required("admin")
def delete_student(student_id):
    run("DELETE FROM students WHERE id = %s", (student_id,))
    flash("Student deleted.", "success")
    return redirect(url_for("students"))


@app.route("/admin/generate-logins", methods=["POST"])
@role_required("admin")
def generate_logins():
    """Create logins for students that don't have one (e.g. imported earlier)."""
    missing = q(
        """
        SELECT s.id, s.name, s.email, s.date_of_birth
        FROM students s LEFT JOIN users u ON u.student_id = s.id
        WHERE u.id IS NULL
        """
    )
    created = skipped = 0
    for s in missing:
        if not s["date_of_birth"]:
            skipped += 1
            continue
        try:
            run(
                """
                INSERT INTO users
                (name, email, password_hash, role, student_id, must_change_password)
                VALUES (%s, %s, %s, 'student', %s, 1)
                """,
                (s["name"], s["email"].lower(), hash_pw(dob_password(s["date_of_birth"])), s["id"]),
            )
            created += 1
        except mysql.connector.Error:
            skipped += 1

    flash(f"Created {created} login(s). Skipped {skipped} (missing date of birth or duplicate email).", "success")
    return redirect(url_for("students"))


@app.route("/admin/users/<int:user_id>/reset", methods=["POST"])
@role_required("admin")
def reset_password(user_id):
    user = q(
        """
        SELECT u.id, u.role, u.student_id, s.date_of_birth
        FROM users u LEFT JOIN students s ON s.id = u.student_id
        WHERE u.id = %s
        """,
        (user_id,), one=True,
    )
    if not user or user["role"] == "admin":
        abort(404)

    if user["role"] == "student":
        if not user["date_of_birth"]:
            flash("Student has no date of birth set.", "error")
            return redirect(url_for("student_detail", student_id=user["student_id"]))
        new_pw = dob_password(user["date_of_birth"])
        target = url_for("student_detail", student_id=user["student_id"])
        message = "Password reset to date of birth (DDMMYYYY)."
    else:
        new_pw = request.form.get("password", "").strip()
        target = url_for("admin_teachers")
        if len(new_pw) < 6:
            flash("Password must be at least 6 characters.", "error")
            return redirect(target)
        message = "Teacher password reset."

    run(
        "UPDATE users SET password_hash=%s, must_change_password=1 WHERE id=%s",
        (hash_pw(new_pw), user_id),
    )
    flash(message + " They must change it on next login.", "success")
    return redirect(target)


@app.route("/admin/teachers", methods=["GET", "POST"])
@role_required("admin")
def admin_teachers():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not name or not email or len(password) < 6:
            flash("Name, email and a temporary password (6+ characters) are required.", "error")
        else:
            try:
                run(
                    """
                    INSERT INTO users (name, email, password_hash, role, must_change_password)
                    VALUES (%s, %s, %s, 'teacher', 1)
                    """,
                    (name, email, hash_pw(password)),
                )
                flash("Teacher added. They must change the password on first login.", "success")
            except mysql.connector.Error:
                flash("That email is already in use.", "error")
        return redirect(url_for("admin_teachers"))

    teachers = q(
        """
        SELECT u.id, u.name, u.email, COUNT(s.id) AS subjects
        FROM users u LEFT JOIN subjects s ON s.teacher_id = u.id
        WHERE u.role = 'teacher'
        GROUP BY u.id, u.name, u.email
        ORDER BY u.name
        """
    )
    return render_template("admin_teachers.html", teachers=teachers)


@app.route("/admin/teachers/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def delete_teacher(user_id):
    run("DELETE FROM users WHERE id = %s AND role = 'teacher'", (user_id,))
    flash("Teacher deleted. Their subjects are now unassigned.", "success")
    return redirect(url_for("admin_teachers"))


@app.route("/admin/subjects", methods=["GET", "POST"])
@role_required("admin")
def admin_subjects():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        course_id = request.form.get("course_id", "")
        teacher_id = request.form.get("teacher_id") or None
        if not name or not course_id:
            flash("Subject name and course are required.", "error")
        else:
            run(
                "INSERT INTO subjects (name, course_id, teacher_id) VALUES (%s, %s, %s)",
                (name, course_id, teacher_id),
            )
            flash("Subject added.", "success")
        return redirect(url_for("admin_subjects"))

    subjects = q(
        """
        SELECT sub.id, sub.name, sub.teacher_id, c.name AS course, u.name AS teacher
        FROM subjects sub
        JOIN courses c ON c.id = sub.course_id
        LEFT JOIN users u ON u.id = sub.teacher_id
        ORDER BY c.name, sub.name
        """
    )
    return render_template(
        "admin_subjects.html",
        subjects=subjects,
        courses=q("SELECT id, name FROM courses ORDER BY name"),
        teachers=q("SELECT id, name FROM users WHERE role='teacher' ORDER BY name"),
    )


@app.route("/admin/subjects/<int:subject_id>/assign", methods=["POST"])
@role_required("admin")
def assign_teacher(subject_id):
    teacher_id = request.form.get("teacher_id") or None
    run("UPDATE subjects SET teacher_id=%s WHERE id=%s", (teacher_id, subject_id))
    flash("Teacher updated.", "success")
    return redirect(url_for("admin_subjects"))


@app.route("/admin/subjects/<int:subject_id>/delete", methods=["POST"])
@role_required("admin")
def delete_subject(subject_id):
    run("DELETE FROM subjects WHERE id = %s", (subject_id,))
    flash("Subject deleted along with its marks and attendance.", "success")
    return redirect(url_for("admin_subjects"))


@app.route("/admin/courses", methods=["POST"])
@role_required("admin")
def add_course():
    name = request.form.get("name", "").strip()
    if name:
        run("INSERT INTO courses (name) VALUES (%s)", (name,))
        flash("Course added.", "success")
    return redirect(url_for("admin_subjects"))


@app.route("/api/students")
@role_required("admin")
def api_students():
    search = request.args.get("search", "").strip()
    sql = """
        SELECT students.id, students.name, students.email, students.phone,
               students.gender, students.status, courses.name AS course
        FROM students
        INNER JOIN courses ON students.course_id = courses.id
    """
    params = ()
    if search:
        sql += " WHERE students.name LIKE %s OR students.email LIKE %s OR students.phone LIKE %s"
        params = (f"%{search}%",) * 3
    sql += " ORDER BY students.name"
    return jsonify(q(sql, params))


@app.route("/api/students/active")
@role_required("admin")
def active_students_api():
    return jsonify(q(
        """
        SELECT students.id, students.name, students.email, students.phone,
               students.gender, students.address, students.status,
               courses.name AS course
        FROM students
        INNER JOIN courses ON students.course_id = courses.id
        WHERE students.status = 'Active'
        ORDER BY students.name
        """
    ))


# ---------------------------------------------------------------- teacher

def get_subject_or_403(subject_id):
    subject = q(
        """
        SELECT sub.*, c.name AS course
        FROM subjects sub JOIN courses c ON c.id = sub.course_id
        WHERE sub.id = %s
        """,
        (subject_id,), one=True,
    )
    if subject is None:
        abort(404)
    if session["role"] == "teacher" and subject["teacher_id"] != session["user_id"]:
        abort(403)
    return subject


def subject_students(subject):
    return q(
        "SELECT id, name, email FROM students WHERE course_id=%s AND status='Active' ORDER BY name",
        (subject["course_id"],),
    )


def bulk_upsert(sql, rows):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()


@app.route("/teacher")
@role_required("teacher")
def teacher_dashboard():
    subjects = q(
        """
        SELECT sub.id, sub.name, c.name AS course,
               (SELECT COUNT(*) FROM students st
                WHERE st.course_id = sub.course_id AND st.status='Active') AS student_count
        FROM subjects sub JOIN courses c ON c.id = sub.course_id
        WHERE sub.teacher_id = %s
        ORDER BY sub.name
        """,
        (session["user_id"],),
    )
    return render_template(
        "teacher_dashboard.html", subjects=subjects,
        at_risk_count=len(at_risk_rows(session["user_id"])),
        pending_leaves=pending_leave_count(),
    )


@app.route("/subject/<int:subject_id>")
@role_required("teacher", "admin")
def subject_detail(subject_id):
    subject = get_subject_or_403(subject_id)
    students_list = subject_students(subject)

    att = {
        r["student_id"]: r for r in q(
            """
            SELECT student_id, SUM(status='Present') AS present, COUNT(*) AS total
            FROM attendance WHERE subject_id=%s GROUP BY student_id
            """,
            (subject_id,),
        )
    }
    mk = {
        r["student_id"]: r for r in q(
            """
            SELECT student_id, SUM(marks_obtained) AS obtained, SUM(max_marks) AS maxm
            FROM marks WHERE subject_id=%s GROUP BY student_id
            """,
            (subject_id,),
        )
    }

    rows = []
    for s in students_list:
        a, m = att.get(s["id"]), mk.get(s["id"])
        rows.append({
            **s,
            "att_pct": pct(a["present"], a["total"]) if a else None,
            "marks_pct": pct(m["obtained"], m["maxm"]) if m else None,
        })

    return render_template(
        "subject_detail.html", subject=subject, rows=rows, low=LOW_ATTENDANCE
    )


@app.route("/subject/<int:subject_id>/attendance", methods=["GET", "POST"])
@role_required("teacher", "admin")
def subject_attendance(subject_id):
    subject = get_subject_or_403(subject_id)
    students_list = subject_students(subject)

    raw_date = request.values.get("date") or date.today().isoformat()
    try:
        att_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        att_date = date.today()

    if request.method == "POST":
        present = set(request.form.getlist("present"))
        rows = [
            (s["id"], subject_id, att_date,
             "Present" if str(s["id"]) in present else "Absent")
            for s in students_list
        ]
        if rows:
            bulk_upsert(
                """
                INSERT INTO attendance (student_id, subject_id, att_date, status)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE status = VALUES(status)
                """,
                rows,
            )
        flash(f"Attendance saved for {att_date.strftime('%d %b %Y')}.", "success")
        return redirect(url_for("subject_attendance", subject_id=subject_id, date=att_date.isoformat()))

    existing = {
        r["student_id"]: r["status"] for r in q(
            "SELECT student_id, status FROM attendance WHERE subject_id=%s AND att_date=%s",
            (subject_id, att_date),
        )
    }
    return render_template(
        "attendance.html", subject=subject, students=students_list,
        existing=existing, att_date=att_date.isoformat(),
    )


@app.route("/subject/<int:subject_id>/marks", methods=["GET", "POST"])
@role_required("teacher", "admin")
def subject_marks(subject_id):
    subject = get_subject_or_403(subject_id)
    students_list = subject_students(subject)
    exam = (request.values.get("exam_type") or "").strip()

    if request.method == "POST":
        try:
            max_marks = float(request.form.get("max_marks", ""))
        except ValueError:
            max_marks = 0

        if not exam or max_marks <= 0:
            flash("Enter an exam name and a maximum mark above 0.", "error")
            return redirect(url_for("subject_marks", subject_id=subject_id))

        rows, bad = [], False
        for s in students_list:
            raw = request.form.get(f"marks_{s['id']}", "").strip()
            if raw == "":
                continue
            try:
                value = float(raw)
            except ValueError:
                bad = True
                break
            if value < 0 or value > max_marks:
                bad = True
                break
            rows.append((s["id"], subject_id, exam, value, max_marks))

        if bad:
            flash("Marks must be numbers between 0 and the maximum.", "error")
        else:
            if rows:
                bulk_upsert(
                    """
                    INSERT INTO marks (student_id, subject_id, exam_type, marks_obtained, max_marks)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        marks_obtained = VALUES(marks_obtained),
                        max_marks = VALUES(max_marks)
                    """,
                    rows,
                )
            flash(f"Saved marks for {len(rows)} student(s).", "success")
        return redirect(url_for("subject_marks", subject_id=subject_id, exam_type=exam))

    existing, max_marks = {}, 100
    if exam:
        for r in q(
            "SELECT student_id, marks_obtained, max_marks FROM marks WHERE subject_id=%s AND exam_type=%s",
            (subject_id, exam),
        ):
            existing[r["student_id"]] = float(r["marks_obtained"])
            max_marks = float(r["max_marks"])

    exams = [r["exam_type"] for r in q(
        "SELECT DISTINCT exam_type FROM marks WHERE subject_id=%s ORDER BY exam_type",
        (subject_id,),
    )]
    return render_template(
        "marks.html", subject=subject, students=students_list,
        exam=exam, exams=exams, existing=existing, max_marks=max_marks,
    )


@app.route("/subject/<int:subject_id>/export")
@role_required("teacher", "admin")
def subject_export(subject_id):
    subject = get_subject_or_403(subject_id)
    kind = request.args.get("type", "marks")
    out = io.StringIO()
    writer = csv.writer(out)

    if kind == "attendance":
        writer.writerow(["Student", "Email", "Date", "Status"])
        data = q(
            """
            SELECT st.name, st.email, a.att_date, a.status
            FROM attendance a JOIN students st ON st.id = a.student_id
            WHERE a.subject_id=%s ORDER BY a.att_date, st.name
            """,
            (subject_id,),
        )
        for r in data:
            writer.writerow([r["name"], r["email"], r["att_date"], r["status"]])
    else:
        kind = "marks"
        writer.writerow(["Student", "Email", "Exam", "Marks", "Max"])
        data = q(
            """
            SELECT st.name, st.email, m.exam_type, m.marks_obtained, m.max_marks
            FROM marks m JOIN students st ON st.id = m.student_id
            WHERE m.subject_id=%s ORDER BY m.exam_type, st.name
            """,
            (subject_id,),
        )
        for r in data:
            writer.writerow([r["name"], r["email"], r["exam_type"],
                             float(r["marks_obtained"]), float(r["max_marks"])])

    filename = f"{subject['name'].replace(' ', '_')}_{kind}.csv"
    return Response(
        out.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------- student

def student_summary(student_id):
    """Everything a dashboard or report card needs for one student."""
    student = q(
        """
        SELECT s.*, c.name AS course
        FROM students s JOIN courses c ON c.id = s.course_id
        WHERE s.id = %s
        """,
        (student_id,), one=True,
    )
    if student is None:
        return None

    subjects = q(
        """
        SELECT sub.id, sub.name, u.name AS teacher
        FROM subjects sub LEFT JOIN users u ON u.id = sub.teacher_id
        WHERE sub.course_id = %s ORDER BY sub.name
        """,
        (student["course_id"],),
    )
    att = {
        r["subject_id"]: r for r in q(
            """
            SELECT subject_id, SUM(status='Present') AS present, COUNT(*) AS total
            FROM attendance WHERE student_id=%s GROUP BY subject_id
            """,
            (student_id,),
        )
    }
    marks = defaultdict(list)
    for r in q(
        "SELECT subject_id, exam_type, marks_obtained, max_marks FROM marks WHERE student_id=%s ORDER BY id",
        (student_id,),
    ):
        marks[r["subject_id"]].append({
            "exam": r["exam_type"],
            "obtained": float(r["marks_obtained"]),
            "max": float(r["max_marks"]),
        })

    rows = []
    tot_present = tot_classes = 0
    all_obtained = all_max = 0.0
    for sub in subjects:
        a = att.get(sub["id"])
        present = int(a["present"]) if a else 0
        total = int(a["total"]) if a else 0
        tot_present += present
        tot_classes += total

        m = marks.get(sub["id"], [])
        obtained = sum(x["obtained"] for x in m)
        maximum = sum(x["max"] for x in m)
        all_obtained += obtained
        all_max += maximum

        att_pct = pct(present, total)
        marks_pct = pct(obtained, maximum) if m else None
        rows.append({
            **sub,
            "present": present,
            "total": total,
            "att_pct": att_pct,
            "low": att_pct is not None and att_pct < LOW_ATTENDANCE,
            "marks": m,
            "obtained": obtained,
            "max": maximum,
            "marks_pct": marks_pct,
            "grade": grade_for(marks_pct),
            "passed": None if marks_pct is None else marks_pct >= LOW_MARKS,
        })

    graded = [r for r in rows if r["marks_pct"] is not None]
    if not graded:
        result = "Incomplete"
    elif all(r["passed"] for r in graded):
        result = "PASS"
    else:
        result = "FAIL"

    overall_marks = pct(all_obtained, all_max) if all_max else None

    rank = None
    class_size = 0
    if all_max:
        mine = 100 * all_obtained / all_max
        everyone = [
            100 * float(r["o"]) / float(r["mx"]) for r in q(
                """
                SELECT m.student_id, SUM(m.marks_obtained) AS o, SUM(m.max_marks) AS mx
                FROM marks m JOIN students st ON st.id = m.student_id
                WHERE st.course_id = %s
                GROUP BY m.student_id
                """,
                (student["course_id"],),
            ) if r["mx"]
        ]
        class_size = len(everyone)
        rank = 1 + sum(1 for p in everyone if p > mine + 1e-9)

    return {
        "student": student,
        "rows": rows,
        "overall_att": pct(tot_present, tot_classes),
        "overall_marks": overall_marks,
        "overall_grade": grade_for(overall_marks),
        "result": result,
        "rank": rank,
        "class_size": class_size,
    }


@app.route("/me")
@role_required("student")
def student_dashboard():
    summary = student_summary(session["student_id"])  # never taken from the URL
    if summary is None:
        abort(404)

    student = summary["student"]
    rows = summary["rows"]

    announcements = q(
        """
        SELECT a.title, a.body, a.created_at, u.name AS author, c.name AS course
        FROM announcements a
        LEFT JOIN users u ON u.id = a.author_id
        LEFT JOIN courses c ON c.id = a.course_id
        WHERE a.course_id IS NULL OR a.course_id = %s
        ORDER BY a.created_at DESC LIMIT 5
        """,
        (student["course_id"],),
    )
    leaves = q(
        "SELECT * FROM leave_requests WHERE student_id=%s ORDER BY created_at DESC LIMIT 3",
        (student["id"],),
    )
    chart = {
        "labels": [r["name"] for r in rows],
        "marks": [r["marks_pct"] for r in rows],
        "attendance": [r["att_pct"] for r in rows],
    }
    return render_template(
        "student_dashboard.html",
        student=student, rows=rows, chart=chart,
        overall_att=summary["overall_att"], low=LOW_ATTENDANCE,
        summary=summary, announcements=announcements, leaves=leaves,
    )


def render_report(student_id):
    summary = student_summary(student_id)
    if summary is None:
        abort(404)
    return render_template("report_card.html", s=summary, today=date.today(), low=LOW_ATTENDANCE)


@app.route("/me/report")
@role_required("student")
def my_report():
    return render_report(session["student_id"])


@app.route("/student/<int:student_id>/report")
@role_required("admin")
def student_report(student_id):
    return render_report(student_id)


@app.route("/me/leave", methods=["GET", "POST"])
@role_required("student")
def student_leave():
    student_id = session["student_id"]

    if request.method == "POST":
        reason = request.form.get("reason", "").strip()[:255]
        try:
            from_date = datetime.strptime(request.form.get("from_date", ""), "%Y-%m-%d").date()
            to_date = datetime.strptime(request.form.get("to_date", ""), "%Y-%m-%d").date()
        except ValueError:
            from_date = to_date = None

        if not reason or from_date is None:
            flash("Enter both dates and a reason.", "error")
        elif to_date < from_date:
            flash("The end date can't be before the start date.", "error")
        else:
            run(
                "INSERT INTO leave_requests (student_id, from_date, to_date, reason) VALUES (%s, %s, %s, %s)",
                (student_id, from_date, to_date, reason),
            )
            flash("Leave request sent.", "success")
        return redirect(url_for("student_leave"))

    leaves = q(
        """
        SELECT l.*, u.name AS reviewer
        FROM leave_requests l LEFT JOIN users u ON u.id = l.reviewed_by
        WHERE l.student_id = %s ORDER BY l.created_at DESC
        """,
        (student_id,),
    )
    return render_template("student_leave.html", leaves=leaves, today=date.today().isoformat())


# ------------------------------------------- leave review (teacher / admin)

def teacher_course_ids(user_id):
    return {r["course_id"] for r in q("SELECT DISTINCT course_id FROM subjects WHERE teacher_id=%s", (user_id,))}


def pending_leave_count():
    if session["role"] == "teacher":
        return q(
            """
            SELECT COUNT(*) AS n FROM leave_requests l JOIN students st ON st.id = l.student_id
            WHERE l.status='Pending'
              AND st.course_id IN (SELECT course_id FROM subjects WHERE teacher_id=%s)
            """,
            (session["user_id"],), one=True,
        )["n"]
    return q("SELECT COUNT(*) AS n FROM leave_requests WHERE status='Pending'", one=True)["n"]


@app.route("/leaves")
@role_required("teacher", "admin")
def leave_requests():
    sql = """
        SELECT l.*, st.name AS student, c.name AS course, u.name AS reviewer
        FROM leave_requests l
        JOIN students st ON st.id = l.student_id
        JOIN courses c ON c.id = st.course_id
        LEFT JOIN users u ON u.id = l.reviewed_by
    """
    params = ()
    if session["role"] == "teacher":
        sql += " WHERE st.course_id IN (SELECT course_id FROM subjects WHERE teacher_id=%s)"
        params = (session["user_id"],)
    sql += " ORDER BY (l.status='Pending') DESC, l.created_at DESC LIMIT 100"
    return render_template("leaves.html", leaves=q(sql, params))


@app.route("/leaves/<int:leave_id>/<action>", methods=["POST"])
@role_required("teacher", "admin")
def decide_leave(leave_id, action):
    if action not in ("approve", "reject"):
        abort(404)

    leave = q(
        """
        SELECT l.id, l.status, st.course_id
        FROM leave_requests l JOIN students st ON st.id = l.student_id
        WHERE l.id = %s
        """,
        (leave_id,), one=True,
    )
    if leave is None:
        abort(404)
    if session["role"] == "teacher" and leave["course_id"] not in teacher_course_ids(session["user_id"]):
        abort(403)

    if leave["status"] != "Pending":
        flash("That request was already decided.", "error")
    else:
        run(
            "UPDATE leave_requests SET status=%s, reviewed_by=%s WHERE id=%s",
            ("Approved" if action == "approve" else "Rejected", session["user_id"], leave_id),
        )
        flash(f"Leave {action}d.", "success")
    return redirect(url_for("leave_requests"))


# ------------------------------------------------------------ announcements

@app.route("/announcements", methods=["GET", "POST"])
@role_required("teacher", "admin")
def announcements():
    if session["role"] == "teacher":
        courses = q(
            """
            SELECT DISTINCT c.id, c.name FROM subjects s JOIN courses c ON c.id = s.course_id
            WHERE s.teacher_id = %s ORDER BY c.name
            """,
            (session["user_id"],),
        )
    else:
        courses = q("SELECT id, name FROM courses ORDER BY name")

    if request.method == "POST":
        title = request.form.get("title", "").strip()[:150]
        body = request.form.get("body", "").strip()[:2000]
        course_id = request.form.get("course_id") or None

        if not title or not body:
            flash("Title and message are required.", "error")
        elif course_id is None and session["role"] != "admin":
            flash("Choose a course for this notice.", "error")
        elif course_id is not None and course_id not in {str(c["id"]) for c in courses}:
            abort(403)
        else:
            run(
                "INSERT INTO announcements (title, body, author_id, course_id) VALUES (%s, %s, %s, %s)",
                (title, body, session["user_id"], course_id),
            )
            flash("Announcement posted.", "success")
        return redirect(url_for("announcements"))

    sql = """
        SELECT a.id, a.title, a.body, a.created_at, a.author_id, u.name AS author, c.name AS course
        FROM announcements a
        LEFT JOIN users u ON u.id = a.author_id
        LEFT JOIN courses c ON c.id = a.course_id
    """
    params = ()
    if session["role"] == "teacher":
        sql += " WHERE a.author_id = %s"
        params = (session["user_id"],)
    sql += " ORDER BY a.created_at DESC LIMIT 50"
    return render_template("announcements.html", items=q(sql, params), courses=courses)


@app.route("/announcements/<int:item_id>/delete", methods=["POST"])
@role_required("teacher", "admin")
def delete_announcement(item_id):
    if session["role"] == "admin":
        run("DELETE FROM announcements WHERE id = %s", (item_id,))
    else:
        run("DELETE FROM announcements WHERE id = %s AND author_id = %s", (item_id, session["user_id"]))
    flash("Announcement deleted.", "success")
    return redirect(url_for("announcements"))


# ---------------------------------------------------------------- at risk

def at_risk_rows(teacher_id=None):
    """Students under the attendance or marks threshold (scoped to a teacher if given)."""
    scope = " AND sub.teacher_id = %s" if teacher_id else ""
    params = (teacher_id,) if teacher_id else ()

    student_sql = """
        SELECT st.id, st.name, c.name AS course
        FROM students st JOIN courses c ON c.id = st.course_id
        WHERE st.status = 'Active'
    """
    if teacher_id:
        student_sql += " AND st.course_id IN (SELECT course_id FROM subjects WHERE teacher_id = %s)"
    student_sql += " ORDER BY st.name"

    att = {
        r["student_id"]: r for r in q(
            """
            SELECT a.student_id, SUM(a.status='Present') AS present, COUNT(*) AS total
            FROM attendance a JOIN subjects sub ON sub.id = a.subject_id
            WHERE 1 = 1""" + scope + " GROUP BY a.student_id",
            params,
        )
    }
    mk = {
        r["student_id"]: r for r in q(
            """
            SELECT m.student_id, SUM(m.marks_obtained) AS obtained, SUM(m.max_marks) AS maxm
            FROM marks m JOIN subjects sub ON sub.id = m.subject_id
            WHERE 1 = 1""" + scope + " GROUP BY m.student_id",
            params,
        )
    }

    rows = []
    for s in q(student_sql, params):
        a, m = att.get(s["id"]), mk.get(s["id"])
        att_pct = pct(a["present"], a["total"]) if a else None
        marks_pct = pct(m["obtained"], m["maxm"]) if m else None
        reasons = []
        if att_pct is not None and att_pct < LOW_ATTENDANCE:
            reasons.append("Low attendance")
        if marks_pct is not None and marks_pct < LOW_MARKS:
            reasons.append("Low marks")
        if reasons:
            rows.append({**s, "att_pct": att_pct, "marks_pct": marks_pct, "reasons": reasons})

    rows.sort(key=lambda r: r["att_pct"] if r["att_pct"] is not None else 101)
    return rows


@app.route("/at-risk")
@role_required("teacher", "admin")
def at_risk():
    teacher_id = session["user_id"] if session["role"] == "teacher" else None
    return render_template(
        "at_risk.html", rows=at_risk_rows(teacher_id),
        low_att=LOW_ATTENDANCE, low_marks=LOW_MARKS,
    )


# -------------------------------------------------------------- analytics

@app.route("/admin/analytics")
@role_required("admin")
def analytics():
    def num(v):
        return None if v is None else round(float(v), 1)

    per_course = q(
        """
        SELECT c.name, COUNT(st.id) AS n
        FROM courses c LEFT JOIN students st ON st.course_id = c.id
        GROUP BY c.id, c.name ORDER BY c.name
        """
    )
    marks_by_subject = q(
        """
        SELECT CONCAT(sub.name, ' (', c.name, ')') AS label,
               100 * SUM(m.marks_obtained) / SUM(m.max_marks) AS value
        FROM subjects sub
        JOIN courses c ON c.id = sub.course_id
        LEFT JOIN marks m ON m.subject_id = sub.id
        GROUP BY sub.id, sub.name, c.name ORDER BY label
        """
    )
    att_by_subject = q(
        """
        SELECT CONCAT(sub.name, ' (', c.name, ')') AS label,
               100 * SUM(a.status='Present') / COUNT(a.id) AS value
        FROM subjects sub
        JOIN courses c ON c.id = sub.course_id
        LEFT JOIN attendance a ON a.subject_id = sub.id
        GROUP BY sub.id, sub.name, c.name ORDER BY label
        """
    )
    data = {
        "courses": {"labels": [r["name"] for r in per_course], "values": [r["n"] for r in per_course]},
        "marks": {"labels": [r["label"] for r in marks_by_subject], "values": [num(r["value"]) for r in marks_by_subject]},
        "attendance": {"labels": [r["label"] for r in att_by_subject], "values": [num(r["value"]) for r in att_by_subject]},
    }
    return render_template("analytics.html", data=data, low=LOW_ATTENDANCE)


# ------------------------------------------------------------------ about

@app.route("/about")
def about():
    return render_template("about.html")


if __name__ == "__main__":
    app.run(debug=True)