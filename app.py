import hashlib
import io
import base64
import secrets
import os
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, make_response, flash, abort)

from models import db, Teacher, Student, Lesson, AttendanceMark

try:
    import qrcode
    _HAS_QRCODE = hasattr(qrcode, 'make')
except Exception:
    _HAS_QRCODE = False


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)


# ---------- Список класса (порядок важен!) ----------

CLASS_ID = '11ВГ'

STUDENTS_LIST = [
    'Алиева Кристина',
    'Антипенков Владимир',
    'Воронина Вероника',
    'Грунин Алексей',
    'Дьяченко Глеб',
    'Евдокимова Светлана',
    'Егоров Григорий',
    'Иванов Артём',
    'Камалов Мухаммадсаид',
    'Карпинская Ульяна',
    'Кейян Роман',
    'Клеянкина Владислава',
    'Козырь Анастасия',
    'Корниенко Константин',
    'Косов Павел',
    'Коханенко Ярослав',
    'Кроль Изабелла',
    'Кужелева Кристина',
    'Леонова Наталья',
    'Малышева Елизавета',
    'Матевосов Александр',
    'Мирзоян Даниэль',
    'Молов Мурат',
    'Мосидзе Родион',
    'Орлов Борис',
    'Павлова Мария',
    'Петров Вадим',
    'Петрухин Алексей',
    'Себенцова Вера',
    'Сотников Даниил',
    'Судакова Дарья',
    'Сухова Ульяна',
    'Талабаев Сергей',
    'Тишаков Илья',
    'Флатов Тимофей',
    'Фрольцов Филипп',
    'Ходов Алексей',
    'Цыбуля Валерий',
    'Чугуевский Григорий',
    'Шульпин Евгений',
    'Шумский Михаил',
    'Эскин Михаил',
    'Юдаева Мария',
]

# Кто всегда присутствует (автоотметка при старте урока)
ALWAYS_PRESENT = {'Воронина Вероника'}


# ---------- Утилиты ----------

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def make_qr_base64(data: str) -> str:
    if _HAS_QRCODE:
        img = qrcode.make(data)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    from urllib.parse import quote
    return f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={quote(data)}"


def teacher_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('teacher_id'):
            return redirect(url_for('teacher_login'))
        return f(*args, **kwargs)
    return wrapper


def get_student_by_device():
    token = request.cookies.get('device_token')
    if not token:
        return None
    return Student.query.filter_by(
        device_token_hash=hash_token(token), is_active=True
    ).first()


def abort_404():
    abort(404)


def get_class_students(class_id):
    """Возвращает учеников класса в исходном порядке (по sort_order, потом по id)."""
    return (Student.query
            .filter_by(class_id=class_id, is_active=True)
            .order_by(Student.sort_order.asc(), Student.id.asc())
            .all())


# ---------- Главная ----------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/join')
def join():
    return redirect(url_for('student_register'))


# ---------- Панель преподавателя ----------

@app.route('/teacher/login', methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        teacher = Teacher.query.filter_by(username=username).first()
        if teacher and teacher.password_hash == hashlib.sha256(password.encode()).hexdigest():
            session['teacher_id'] = teacher.id
            return redirect(url_for('teacher_dashboard'))
        flash('Неверный логин или пароль')
    return render_template('teacher_login.html')


@app.route('/teacher/logout')
def teacher_logout():
    session.pop('teacher_id', None)
    return redirect(url_for('index'))


@app.route('/teacher/dashboard')
@teacher_required
def teacher_dashboard():
    teacher = db.session.get(Teacher, session['teacher_id'])
    lessons = (Lesson.query
               .filter_by(teacher_id=teacher.id)
               .order_by(Lesson.started_at.desc())
               .limit(20).all())
    return render_template('teacher_dashboard.html',
                           teacher=teacher,
                           lessons=lessons,
                           default_class=CLASS_ID)


@app.route('/teacher/lesson/start', methods=['POST'])
@teacher_required
def start_lesson():
    class_id = request.form['class_id'].strip()
    subject = request.form['subject'].strip()
    if not class_id or not subject:
        flash('Заполните класс и предмет')
        return redirect(url_for('teacher_dashboard'))

    lesson = Lesson(
        teacher_id=session['teacher_id'],
        class_id=class_id,
        subject=subject,
        token=Lesson.generate_token(),
        is_active=True,
    )
    db.session.add(lesson)
    db.session.flush()  # чтобы получить lesson.id

    # Автоотметка для "всегда присутствующих"
    students = get_class_students(class_id)
    for s in students:
        if s.full_name in ALWAYS_PRESENT:
            db.session.add(AttendanceMark(
                lesson_id=lesson.id,
                student_id=s.id,
                method='auto',
            ))

    db.session.commit()
    return redirect(url_for('lesson_active', lesson_id=lesson.id))


@app.route('/teacher/lesson/<int:lesson_id>')
@teacher_required
def lesson_active(lesson_id):
    lesson = db.session.get(Lesson, lesson_id) or abort_404()
    if lesson.teacher_id != session['teacher_id']:
        return "Forbidden", 403

    mark_url = url_for('student_mark', token=lesson.token, _external=True)
    qr_data = make_qr_base64(mark_url)

    students = get_class_students(lesson.class_id)
    marked_ids = {m.student_id for m in lesson.marks}
    present = [s for s in students if s.id in marked_ids]
    absent = [s for s in students if s.id not in marked_ids]

    return render_template('lesson_active.html',
                           lesson=lesson, qr_data=qr_data,
                           mark_url=mark_url,
                           present=present, absent=absent,
                           students=students,
                           always_present=ALWAYS_PRESENT)


@app.route('/teacher/lesson/<int:lesson_id>/finish', methods=['POST'])
@teacher_required
def finish_lesson(lesson_id):
    lesson = db.session.get(Lesson, lesson_id) or abort_404()
    if lesson.teacher_id != session['teacher_id']:
        return "Forbidden", 403
    lesson.is_active = False
    lesson.finished_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for('lesson_result', lesson_id=lesson.id))


@app.route('/teacher/lesson/<int:lesson_id>/result')
@teacher_required
def lesson_result(lesson_id):
    lesson = db.session.get(Lesson, lesson_id) or abort_404()
    if lesson.teacher_id != session['teacher_id']:
        return "Forbidden", 403

    students = get_class_students(lesson.class_id)
    marked_ids = {m.student_id for m in lesson.marks}
    present = [s for s in students if s.id in marked_ids]
    absent = [s for s in students if s.id not in marked_ids]
    return render_template('lesson_result.html',
                           lesson=lesson, present=present, absent=absent)


@app.route('/teacher/lesson/<int:lesson_id>/manual', methods=['POST'])
@teacher_required
def manual_mark(lesson_id):
    lesson = db.session.get(Lesson, lesson_id) or abort_404()
    if lesson.teacher_id != session['teacher_id']:
        return "Forbidden", 403
    student_id = int(request.form['student_id'])
    exists = AttendanceMark.query.filter_by(
        lesson_id=lesson.id, student_id=student_id).first()
    if not exists:
        db.session.add(AttendanceMark(
            lesson_id=lesson.id, student_id=student_id, method='manual'))
        db.session.commit()
    return redirect(url_for('lesson_active', lesson_id=lesson.id))


@app.route('/teacher/lesson/<int:lesson_id>/unmark', methods=['POST'])
@teacher_required
def unmark(lesson_id):
    lesson = db.session.get(Lesson, lesson_id) or abort_404()
    if lesson.teacher_id != session['teacher_id']:
        return "Forbidden", 403
    student_id = int(request.form['student_id'])
    mark = AttendanceMark.query.filter_by(
        lesson_id=lesson.id, student_id=student_id).first()
    if mark:
        db.session.delete(mark)
        db.session.commit()
    return redirect(url_for('lesson_active', lesson_id=lesson.id))


@app.route('/teacher/lesson/<int:lesson_id>/export')
@teacher_required
def export_txt(lesson_id):
    lesson = db.session.get(Lesson, lesson_id) or abort_404()
    if lesson.teacher_id != session['teacher_id']:
        return "Forbidden", 403

    students = get_class_students(lesson.class_id)
    marked_ids = {m.student_id for m in lesson.marks}
    present = [s for s in students if s.id in marked_ids]
    absent = [s for s in students if s.id not in marked_ids]

    lines = []
    lines.append(f"Урок: {lesson.subject}")
    lines.append(f"Класс: {lesson.class_id}")
    lines.append(f"Дата: {lesson.started_at.strftime('%d.%m.%Y %H:%M')}")
    if lesson.finished_at:
        lines.append(f"Завершён: {lesson.finished_at.strftime('%d.%m.%Y %H:%M')}")
    lines.append("")
    lines.append(f"Всего учеников: {len(students)}")
    lines.append(f"Присутствовали: {len(present)}")
    lines.append(f"Отсутствовали: {len(absent)}")
    lines.append("")
    lines.append("=== ПРИСУТСТВОВАЛИ ===")
    if present:
        for i, s in enumerate(present, 1):
            lines.append(f"{i}. {s.display_name}")
    else:
        lines.append("(нет)")
    lines.append("")
    lines.append("=== ОТСУТСТВОВАЛИ ===")
    if absent:
        for i, s in enumerate(absent, 1):
            lines.append(f"{i}. {s.display_name}")
    else:
        lines.append("(нет)")
    lines.append("")

    text = "\r\n".join(lines)
    resp = make_response(text)
    resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    resp.headers['Content-Disposition'] = \
        f'attachment; filename=lesson_{lesson.id}.txt'
    return resp


# ---------- Ученик ----------

@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        class_id = request.form['class_id'].strip()

        if not full_name or not class_id:
            flash('Заполните все поля')
            return render_template('student_register.html', default_class=CLASS_ID)

        # нормализуем: убираем лишние пробелы, приводим к нижнему регистру
        def normalize(s):
            return ' '.join(s.lower().split())

        target_name = normalize(full_name)
        target_class = normalize(class_id)

        # ищем ученика этого класса без учёта регистра
        student = None
        for s in Student.query.filter_by(is_active=True).all():
            if normalize(s.class_id) == target_class and normalize(s.full_name) == target_name:
                student = s
                break

        if not student:
            flash('Ученик не найден. Обратитесь к преподавателю.')
            return render_template('student_register.html', default_class=CLASS_ID)

        if student.device_token_hash:
            flash('Этот ученик уже зарегистрирован на другом устройстве. '
                  'Обратитесь к преподавателю для сброса.')
            return render_template('student_register.html', default_class=CLASS_ID)

        token = secrets.token_urlsafe(32)
        student.device_token_hash = hash_token(token)
        db.session.commit()

        resp = redirect(url_for('student_home'))
        resp.set_cookie('device_token', token,
                        max_age=60 * 60 * 24 * 365,
                        httponly=True, samesite='Lax')
        return resp

    return render_template('student_register.html', default_class=CLASS_ID)


@app.route('/student/')
def student_home():
    student = get_student_by_device()
    if not student:
        return redirect(url_for('student_register'))
    return render_template('student_home.html', student=student)


@app.route('/mark/<token>')
def student_mark(token):
    student = get_student_by_device()
    if not student:
        return redirect(url_for('student_register'))

    lesson = Lesson.query.filter_by(token=token).first()
    if not lesson:
        return render_template('student_mark.html',
                               error='QR-код недействителен.')

    if not lesson.is_active:
        return render_template('student_mark.html',
                               error='Урок уже завершён.', lesson=lesson)

    if lesson.class_id != student.class_id:
        return render_template('student_mark.html',
                               error='Вы не относитесь к этому классу.',
                               lesson=lesson)

    existing = AttendanceMark.query.filter_by(
        lesson_id=lesson.id, student_id=student.id).first()

    if not existing:
        db.session.add(AttendanceMark(
            lesson_id=lesson.id, student_id=student.id, method='qr'))
        db.session.commit()

    return render_template('student_mark.html',
                           success=True, lesson=lesson, student=student,
                           already=bool(existing))


@app.route('/teacher/student/<int:student_id>/reset_device', methods=['POST'])
@teacher_required
def reset_device(student_id):
    student = db.session.get(Student, student_id) or abort_404()
    student.device_token_hash = None
    db.session.commit()
    flash(f'Привязка устройства для {student.display_name} сброшена.')
    return redirect(request.referrer or url_for('teacher_dashboard'))


# ---------- Инициализация ----------

def init_db():
    with app.app_context():
        db.create_all()

        if not Teacher.query.first():
            t = Teacher(
                username='teacher',
                password_hash=hashlib.sha256(b'qwerty123123').hexdigest(),
                full_name='Преподаватель',
            )
            db.session.add(t)

        if not Student.query.first():
            for i, name in enumerate(STUDENTS_LIST):
                db.session.add(Student(
                    full_name=name,
                    class_id=CLASS_ID,
                    sort_order=i,
                ))

        db.session.commit()
        print(f'БД инициализирована. Класс {CLASS_ID}: {len(STUDENTS_LIST)} учеников.')
        print('Логин: teacher / qwerty123123')


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)