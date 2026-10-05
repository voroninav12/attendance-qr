from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import secrets

db = SQLAlchemy()


class Teacher(db.Model):
    __tablename__ = 'teachers'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(200))
    lessons = db.relationship('Lesson', backref='teacher', lazy=True)


class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False)
    class_id = db.Column(db.String(20), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    device_token_hash = db.Column(db.String(128), unique=True, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def display_name(self):
        return self.full_name


class Lesson(db.Model):
    __tablename__ = 'lessons'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    class_id = db.Column(db.String(20), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    marks = db.relationship('AttendanceMark', backref='lesson', lazy=True,
                            cascade="all, delete-orphan")

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(32)


class AttendanceMark(db.Model):
    __tablename__ = 'attendance_marks'
    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    marked_at = db.Column(db.DateTime, default=datetime.utcnow)
    method = db.Column(db.String(20), default='qr')
    student = db.relationship('Student', backref='marks')

    __table_args__ = (
        db.UniqueConstraint('lesson_id', 'student_id', name='unique_lesson_student'),
    )