
import pandas as pd
from flask import (
    render_template, request, redirect, url_for, flash, send_file, 
    Blueprint, jsonify
)
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, time, timedelta
from sqlalchemy import or_
import io
from collections import defaultdict
import json

from . import db, bcrypt, login_manager
from .models import User, Jadwal, Gedung, Lantai, Ruangan

bp = Blueprint('routes', __name__)

generate_progress_status = {
    'total_items': 0,
    'processed_items': 0,
    'status': 'idle',
    'message': ''
}

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def parse_time(t_str):
    try:
        if isinstance(t_str, time): return t_str
        return datetime.strptime(str(t_str), "%H:%M").time()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(str(t_str), "%H.%M").time()
        except (ValueError, TypeError):
            try:
                return datetime.strptime(str(t_str), "%H:%M:%S").time()
            except (ValueError, TypeError):
                return None

def is_bentrok(hari, mulai_baru, selesai_baru, ruangan_id, kelas, nama_dosen_baru, tipe_kelas):
    mulai_baru_time = parse_time(mulai_baru)
    selesai_baru_time = parse_time(selesai_baru)
    if not (mulai_baru_time and selesai_baru_time):
        return False

    conflicting_schedules = Jadwal.query.filter(
        Jadwal.hari == hari,
        db.func.time(Jadwal.jam_selesai) > mulai_baru_time,
        db.func.time(Jadwal.jam_mulai) < selesai_baru_time
    ).all()

    for sched in conflicting_schedules:
        if tipe_kelas == 'Offline' and sched.tipe_kelas == 'Offline' and sched.ruangan_id == int(ruangan_id):
            flash(f"Jadwal bentrok: Ruangan '{sched.ruangan}' sudah dipakai oleh '{sched.mata_kuliah}' pada jam tersebut.", "danger")
            return True
        if sched.kelas == kelas:
            flash(f"Jadwal bentrok: Kelas '{kelas}' sudah ada jadwal lain ('{sched.mata_kuliah}') pada jam tersebut.", "danger")
            return True
        if sched.nama_dosen == nama_dosen_baru:
            flash(f"Jadwal bentrok: Dosen '{nama_dosen_baru}' sudah mengajar di kelas lain ('{sched.mata_kuliah}') pada jam tersebut.", "danger")
            return True
            
    return False

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('routes.landing_page'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and bcrypt.check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('routes.landing_page'))
        else: flash('Login gagal. Periksa kembali username dan password Anda.', 'danger')
    return render_template('login.html')

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('routes.landing_page'))
    if request.method == 'POST':
        username = request.form.get('username')
        if User.query.filter_by(username=username).first():
            flash('Username sudah digunakan.', 'warning')
            return redirect(url_for('routes.register'))
        hashed_password = bcrypt.generate_password_hash(request.form.get('password')).decode('utf-8')
        new_user = User(username=username, password=hashed_password, role='dosen') #
        db.session.add(new_user)
        db.session.commit()
        flash('Akun dosen Anda berhasil dibuat! Silakan login.', 'success')
        return redirect(url_for('routes.login'))
    return render_template('register.html')

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('routes.login'))

@bp.route('/')
@login_required
def landing_page():
    return render_template('landing_page.html')

@bp.route('/booking', methods=['GET'])
@login_required
def halaman_booking():
    if current_user.role == 'mahasiswa':
        flash('Anda tidak memiliki hak akses untuk halaman ini.', 'warning'); return redirect(url_for('routes.landing_page'))
    
    form_data = {'dosen': current_user.username} if current_user.role == 'dosen' else {} #
    if request.args:
        form_data['hari'] = request.args.get('day', form_data.get('hari', ''))
        form_data['jam_mulai'] = request.args.get('start_time', form_data.get('jam_mulai', ''))
        form_data['jam_selesai'] = request.args.get('end_time', form_data.get('jam_selesai', ''))
        ruangan_nama = request.args.get('room', '')
        if ruangan_nama:
            ruangan_obj = Ruangan.query.filter_by(nama_ruangan=ruangan_nama).first()
            if ruangan_obj:
                # Kirim ID ke template untuk pre-selection
                form_data['ruangan'] = ruangan_obj.id 
                form_data['lantai'] = ruangan_obj.lantai.id
                form_data['gedung'] = ruangan_obj.lantai.gedung.id
        form_data['tipe_kelas'] = 'Offline'
    
    if 'tipe_kelas' not in form_data:
        form_data['tipe_kelas'] = 'Offline'
        
    return render_template('booking_form.html', form_data=form_data)

@bp.route('/submit_booking', methods=['POST'])
@login_required
def submit_booking():
    if current_user.role == 'mahasiswa': return redirect(url_for('routes.landing_page'))
    form = request.form
    
    # Ambil data form
    tipe_kelas = form.get('tipe_kelas')
    ruangan_id = form.get('ruangan') if tipe_kelas == 'Offline' else None
    
    # Validasi
    if is_bentrok(form.get('hari'), form.get('jam_mulai'), form.get('jam_selesai'), ruangan_id, form.get('kelas'), form.get('dosen'), tipe_kelas):
        # Flash message sudah di-handle di dalam fungsi is_bentrok
        return redirect(url_for('routes.halaman_booking'))
    
    new_jadwal = Jadwal(
        nama_dosen=form.get('dosen'),
        mata_kuliah=form.get('matkul'),
        kelas=form.get('kelas'),
        sks=int(form.get('sks', 0)),
        hari=form.get('hari'),
        jam_mulai=form.get('jam_mulai'),
        jam_selesai=form.get('jam_selesai'),
        tipe_kelas=tipe_kelas,
        ruangan_id=ruangan_id,
        user_id=current_user.id
    )
    db.session.add(new_jadwal)
    db.session.commit()
    flash('Booking berhasil disimpan!', 'success')
    return redirect(url_for('routes.halaman_jadwal'))

@bp.route('/jadwal')
@login_required
def halaman_jadwal():
    filter_by = request.args.get('filter_by', 'Hari')
    filter_value = request.args.get('filter_value', '').strip()
    query = Jadwal.query
    if filter_value:
        if filter_by == 'Hari':
            query = query.filter(Jadwal.hari.ilike(f'%{filter_value}%'))
        elif filter_by == 'Kelas':
            query = query.filter(Jadwal.kelas.ilike(f'%{filter_value}%'))
        elif filter_by == 'Dosen':
            query = query.filter(Jadwal.nama_dosen.ilike(f'%{filter_value}%'))
        elif filter_by == 'Ruangan':
            query = query.join(Ruangan).filter(Ruangan.nama_ruangan.ilike(f'%{filter_value}%'))

    jadwal_list = query.order_by(Jadwal.id.desc()).all()
    header = ["ID", "Dosen", "Matkul", "SKS", "Kelas", "Hari", "Mulai", "Selesai",
              "Gedung", "Lantai", "Ruangan", "Tipe"]
    return render_template('view_jadwal.html', header=header, jadwal_list=jadwal_list,
                           filter_by=filter_by, filter_value=filter_value)

# ... Rute lain seperti generate, import, ruangan_tersedia, delete, download ...
# Kode untuk rute-rute ini perlu diadaptasi dari app.py lama Anda
# dan disesuaikan untuk menggunakan model database baru.

### API ENDPOINTS ###
@bp.route('/api/gedung')
@login_required
def api_gedung():
    gedung_list = Gedung.query.order_by(Gedung.nama_gedung).all()
    return jsonify([{'id': g.id, 'nama': g.nama_gedung} for g in gedung_list])

@bp.route('/api/lantai/<int:gedung_id>')
@login_required
def api_lantai(gedung_id):
    lantai_list = Lantai.query.filter_by(gedung_id=gedung_id).order_by(Lantai.nama_lantai).all()
    return jsonify([{'id': l.id, 'nama': l.nama_lantai} for l in lantai_list])

@bp.route('/api/ruangan/<int:lantai_id>')
@login_required
def api_ruangan(lantai_id):
    ruangan_list = Ruangan.query.filter_by(lantai_id=lantai_id).order_by(Ruangan.nama_ruangan).all()
    return jsonify([{'id': r.id, 'nama': r.nama_ruangan} for r in ruangan_list])

### ADMIN ROUTES ###
@bp.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash("Hanya admin yang bisa mengakses halaman ini.", "danger")
        return redirect(url_for('routes.landing_page'))
    user_count = User.query.count()
    jadwal_count = Jadwal.query.count()
    ruangan_count = Ruangan.query.count()
    return render_template('admin/dashboard.html', user_count=user_count, jadwal_count=jadwal_count, ruangan_count=ruangan_count)

@bp.route('/admin/gedung', methods=['GET', 'POST'])
@login_required
def manage_gedung():
    if current_user.role != 'admin': return redirect(url_for('routes.landing_page'))
    if request.method == 'POST':
        nama_gedung = request.form.get('nama_gedung')
        if nama_gedung:
            if not Gedung.query.filter_by(nama_gedung=nama_gedung).first():
                db.session.add(Gedung(nama_gedung=nama_gedung))
                db.session.commit()
                flash(f"Gedung '{nama_gedung}' berhasil ditambahkan.", "success")
            else:
                flash(f"Gedung '{nama_gedung}' sudah ada.", "warning")
        return redirect(url_for('routes.manage_gedung'))
    
    all_gedung = Gedung.query.all()
    return render_template('admin/manage_gedung.html', all_gedung=all_gedung)

@bp.route('/admin/gedung/delete/<int:id>', methods=['POST'])
@login_required
def delete_gedung(id):
    if current_user.role != 'admin': return redirect(url_for('routes.landing_page'))
    gedung = Gedung.query.get_or_404(id)
    db.session.delete(gedung)
    db.session.commit()
    flash(f"Gedung '{gedung.nama_gedung}' berhasil dihapus.", "success")
    return redirect(url_for('routes.manage_gedung'))

# --- RUTE UNTUK GENERATE DAN IMPORT ---

@bp.route('/generate')
@login_required
def halaman_generate():
    if current_user.role != 'admin':
        flash("Hanya admin yang bisa mengakses halaman ini.", "danger")
        return redirect(url_for('routes.landing_page'))
    # Logika untuk halaman generate jadwal otomatis ada di sini
    # Untuk saat ini, kita hanya akan merender template-nya
    return render_template('generate_jadwal.html')

@bp.route('/generate/start', methods=['POST'])
@login_required
def start_generation():
    # Logika kompleks dari 'halaman_generate' lama akan ada di sini
    # Karena sangat kompleks dan memerlukan adaptasi besar ke database baru,
    # kita akan menampilkan pesan bahwa fitur ini dalam pengembangan.
    flash("Fitur Generate Jadwal Otomatis sedang dalam pengembangan lanjut.", "info")
    return redirect(url_for('routes.halaman_generate'))


@bp.route('/import', methods=['GET', 'POST'])
@login_required
def halaman_import():
    if current_user.role != 'admin':
        flash("Hanya admin yang bisa mengakses halaman ini.", "danger")
        return redirect(url_for('routes.landing_page'))

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('Tidak ada file yang dipilih.', 'warning')
            return redirect(request.url)

        try:
            df = pd.read_excel(file) if file.filename.endswith('.xlsx') else pd.read_csv(file)
            required_columns = ['Nama Dosen', 'Mata Kuliah', 'SKS', 'Kelas', 'Hari', 'Jam Mulai', 'Jam Selesai', 'Tipe Kelas']
            if not all(col in df.columns for col in required_columns):
                flash(f"File harus memiliki kolom: {', '.join(required_columns)}", 'danger')
                return redirect(request.url)

            jadwal_ditambahkan = 0
            jadwal_bentrok = 0
            for _, row in df.iterrows():
                # Cek bentrok sebelum menambahkan
                ruangan_id = None
                if row['Tipe Kelas'] == 'Offline':
                    ruangan = Ruangan.query.filter_by(nama_ruangan=row.get('Ruangan')).first()
                    if ruangan:
                        ruangan_id = ruangan.id
                    else:
                        # Jika ruangan tidak ditemukan, lewati atau beri pesan error
                        continue 

                if not is_bentrok(row['Hari'], row['Jam Mulai'], row['Jam Selesai'], ruangan_id, row['Kelas'], row['Nama Dosen'], row['Tipe Kelas']):
                    new_jadwal = Jadwal(
                        nama_dosen=row['Nama Dosen'],
                        mata_kuliah=row['Mata Kuliah'],
                        sks=row['SKS'],
                        kelas=row['Kelas'],
                        hari=row['Hari'],
                        jam_mulai=row['Jam Mulai'],
                        jam_selesai=row['Jam Selesai'],
                        tipe_kelas=row['Tipe Kelas'],
                        ruangan_id=ruangan_id,
                        user_id=current_user.id
                    )
                    db.session.add(new_jadwal)
                    jadwal_ditambahkan += 1
                else:
                    jadwal_bentrok += 1
            
            db.session.commit()
            flash(f"Import selesai! {jadwal_ditambahkan} jadwal berhasil ditambahkan. {jadwal_bentrok} jadwal dilewati karena bentrok.", 'success')

        except Exception as e:
            db.session.rollback()
            flash(f"Terjadi error saat import file: {e}", 'danger')
        
        return redirect(url_for('routes.halaman_jadwal'))
        
    return render_template('import_jadwal.html')