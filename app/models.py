from . import db
from flask_login import UserMixin

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(80), nullable=False, default='dosen')

class Gedung(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_gedung = db.Column(db.String(50), unique=True, nullable=False)
    lantai = db.relationship('Lantai', backref='gedung', cascade="all, delete-orphan", lazy=True)

class Lantai(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_lantai = db.Column(db.String(50), nullable=False)
    gedung_id = db.Column(db.Integer, db.ForeignKey('gedung.id'), nullable=False)
    ruangan = db.relationship('Ruangan', backref='lantai', cascade="all, delete-orphan", lazy=True)

class Ruangan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_ruangan = db.Column(db.String(100), unique=True, nullable=False)
    kategori = db.Column(db.String(50), nullable=False, default='Kelas')
    lantai_id = db.Column(db.Integer, db.ForeignKey('lantai.id'), nullable=False)
    jadwal = db.relationship('Jadwal', backref='ruangan_obj', lazy=True)

class Jadwal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_dosen = db.Column(db.String(120), nullable=False)
    mata_kuliah = db.Column(db.String(120), nullable=False)
    sks = db.Column(db.Integer, nullable=False, default=0)
    kelas = db.Column(db.String(80), nullable=False)
    hari = db.Column(db.String(20), nullable=False)
    jam_mulai = db.Column(db.String(5), nullable=False)
    jam_selesai = db.Column(db.String(5), nullable=False)
    tipe_kelas = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    ruangan_id = db.Column(db.Integer, db.ForeignKey('ruangan.id'), nullable=True)
    user = db.relationship('User', backref='jadwal')

    @property
    def gedung(self):
        if self.tipe_kelas == 'Online' or not self.ruangan_obj:
            return 'Online'
        return self.ruangan_obj.lantai.gedung.nama_gedung

    @property
    def lantai(self):
        if self.tipe_kelas == 'Online' or not self.ruangan_obj:
            return 'N/A'
        return self.ruangan_obj.lantai.nama_lantai
        
    @property
    def ruangan(self):
        if self.tipe_kelas == 'Online' or not self.ruangan_obj:
            return 'Online'
        return self.ruangan_obj.nama_ruangan