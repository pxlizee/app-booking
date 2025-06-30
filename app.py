import os
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from datetime import datetime, time, timedelta
from sqlalchemy import or_
import io
from collections import defaultdict
import json

# --- Inisialisasi & Konfigurasi Aplikasi ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'proyek-final-ini-sudah-selesai-dan-bekerja'
db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'database.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Silakan login untuk mengakses halaman ini.'
login_manager.login_message_category = 'info'

# --- Data Statis Aplikasi ---
data_gedung = {
    "A": {
        "3": ["Lab Komputer Mesin 1", "Lab Komputer Mesin 2", "A3A"],
        "4": ["Lab Komputer Hardware", "Lab Komputer Software", "A4A"],
        "5": ["Lab Komputer DKV 1", "Lab Komputer DKV 2", "A5A"]
    },
    "B": {
        "1": ["Lab Teknik Sipil", "Lab Teknik Elektro"],
        "2": [f"B2{huruf}" for huruf in "ABCDEFGH"],
        "3": [f"B3{huruf}" for huruf in "ABCDEFGH"],
        "4": [f"B4{huruf}" for huruf in "ABCDEFGH"],
        "5": [f"B5{huruf}" for huruf in "ABCDEFGH"]
    }
}
HARI_LIST = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
ALLOWED_LANTAI3_ROOMS = ['B3A', 'B3B', 'B3C', 'B3D', 'B3E', 'B3F', 'B3G', 'B3H']
EXCLUDED_LAB_ROOMS_FOR_GENERATION = set([
    "Lab Komputer Hardware", "Lab Komputer Software",
    "Lab Komputer Mesin 1", "Lab Komputer Mesin 2",
    "Lab Komputer DKV 1", "Lab Komputer DKV 2",
    "Lab Teknik Sipil", "Lab Teknik Elektro"
])

# Variabel global untuk progres generate
generate_progress_status = {
    'total_items': 0, 'processed_items': 0, 'status': 'idle', 'message': ''
}

# --- Model Database ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(80), nullable=False)

class Jadwal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_dosen = db.Column(db.String(120), nullable=False)
    mata_kuliah = db.Column(db.String(120), nullable=False)
    kelas = db.Column(db.String(80), nullable=False)
    hari = db.Column(db.String(20), nullable=False)
    jam_mulai = db.Column(db.String(5), nullable=False)
    jam_selesai = db.Column(db.String(5), nullable=False)
    gedung = db.Column(db.String(20))
    lantai = db.Column(db.String(20))
    ruangan = db.Column(db.String(80))
    tipe_kelas = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    sks = db.Column(db.Integer, nullable=False, default=0)

# --- Fungsi Inti & Bantuan ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def parse_time(t_str):
    formats_to_try = ["%H:%M", "%H.%M", "%H:%M:%S"]
    for fmt in formats_to_try:
        try:
            return datetime.strptime(str(t_str), fmt).time()
        except (ValueError, TypeError):
            continue
    return None

def is_bentrok(hari, mulai_baru, selesai_baru, ruangan, kelas, nama_dosen_baru, tipe_kelas, jadwal_id_to_ignore=None):
    mulai_baru_time = parse_time(mulai_baru)
    selesai_baru_time = parse_time(selesai_baru)
    if not (mulai_baru_time and selesai_baru_time):
        return False

    query = Jadwal.query.filter(
        Jadwal.hari == hari,
        Jadwal.id != jadwal_id_to_ignore,
        db.func.time(Jadwal.jam_selesai) > mulai_baru_time,
        db.func.time(Jadwal.jam_mulai) < selesai_baru_time
    )
    
    conditions = []
    conditions.append(Jadwal.kelas == kelas)
    conditions.append(Jadwal.nama_dosen == nama_dosen_baru)
    if tipe_kelas == 'Offline':
        conditions.append(db.and_(Jadwal.ruangan == ruangan, Jadwal.tipe_kelas == 'Offline'))

    konflik = query.filter(or_(*conditions)).first()
    return konflik is not None

def is_bentrok_cached(hari, mulai_baru_time, selesai_baru_time, ruangan, kelas, nama_dosen_baru, tipe_kelas, existing_schedules_cache):
    # Cek bentrok ruangan (hanya jika kelas yang sedang dicek adalah Offline)
    if tipe_kelas == 'Offline' and ruangan != 'N/A':
        for jadwal_existing in existing_schedules_cache['ruangan'].get(hari, {}).get(ruangan, []):
            if parse_time(jadwal_existing.jam_mulai) < selesai_baru_time and parse_time(jadwal_existing.jam_selesai) > mulai_baru_time:
                return True # Bentrok ruangan

    # Cek bentrok kelas
    for jadwal_existing in existing_schedules_cache['kelas'].get(hari, {}).get(kelas, []):
        if parse_time(jadwal_existing.jam_mulai) < selesai_baru_time and parse_time(jadwal_existing.jam_selesai) > mulai_baru_time:
            return True # Bentrok kelas

    # Cek bentrok dosen
    for jadwal_existing in existing_schedules_cache['dosen'].get(hari, {}).get(nama_dosen_baru, []):
        if parse_time(jadwal_existing.jam_mulai) < selesai_baru_time and parse_time(jadwal_existing.jam_selesai) > mulai_baru_time:
            return True # Bentrok dosen

    return False

# --- Rute Otentikasi & Navigasi Utama ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('halaman_jadwal'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and bcrypt.check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('halaman_jadwal'))
        else:
            flash('Login gagal. Periksa kembali username dan password Anda.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('halaman_jadwal'))
    if request.method == 'POST':
        username = request.form.get('username')
        if User.query.filter_by(username=username).first():
            flash('Username sudah digunakan.', 'warning')
            return redirect(url_for('register'))
        hashed_password = bcrypt.generate_password_hash(request.form.get('password')).decode('utf-8')
        new_user = User(username=username, password=hashed_password, role='dosen')
        db.session.add(new_user)
        db.session.commit()
        flash('Akun dosen Anda berhasil dibuat! Silakan login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def landing_page():
    return redirect(url_for('halaman_jadwal'))

# --- Rute Fitur Aplikasi ---

@app.route('/jadwal')
@login_required
def halaman_jadwal():
    filter_by = request.args.get('filter_by', 'Hari')
    filter_value = request.args.get('filter_value', '').strip()
    action = request.args.get('action')

    query = Jadwal.query
    if filter_value:
        if filter_by == 'Hari':
            query = query.filter(Jadwal.hari.ilike(f'%{filter_value}%'))
        elif filter_by == 'Ruangan':
            query = query.filter(Jadwal.ruangan.ilike(f'%{filter_value}%'))
        elif filter_by == 'Kelas':
            query = query.filter(Jadwal.kelas.ilike(f'%{filter_value}%'))
        elif filter_by == 'Dosen':
            query = query.filter(Jadwal.nama_dosen.ilike(f'%{filter_value}%'))

    jadwal_list = query.order_by(Jadwal.id.desc()).all()
    
    form_data = {}
    show_composer = action == 'new'
    if show_composer:
        form_data['hari'] = request.args.get('day', '')
        form_data['ruangan'] = request.args.get('room', '')
        form_data['jam_mulai'] = request.args.get('start_time', '')
        form_data['jam_selesai'] = request.args.get('end_time', '')
        form_data['tipe_kelas'] = request.args.get('tipe_kelas', 'Offline')
        if current_user.role == 'dosen':
            form_data['dosen'] = current_user.username

    return render_template('view_jadwal.html', 
                           jadwal_list=jadwal_list,
                           filter_by=filter_by, 
                           filter_value=filter_value,
                           show_composer=show_composer,
                           form_data=form_data)

@app.route('/submit_booking', methods=['POST'])
@login_required
def submit_booking():
    if current_user.role == 'mahasiswa':
        flash('Aksi tidak diizinkan.', 'danger')
        return redirect(url_for('halaman_jadwal'))
    
    form_data = {k: v.strip() for k, v in request.form.items()}
    
    mulai_time = parse_time(form_data.get('jam_mulai'))
    selesai_time = parse_time(form_data.get('jam_selesai'))
    if not (mulai_time and selesai_time and mulai_time < selesai_time):
        flash("Jam mulai harus lebih kecil dari jam selesai dan formatnya benar.", "danger")
        return redirect(url_for('halaman_jadwal', action='new'))

    if (mulai_time < time(13, 0) and selesai_time > time(12, 0)):
        flash("Jadwal tidak boleh bentrok dengan jam istirahat (12:00 - 13:00).", "danger")
        return redirect(url_for('halaman_jadwal', action='new'))

    tipe_kelas = form_data.get('tipe_kelas')
    ruangan = form_data.get('ruangan') if tipe_kelas == 'Offline' else 'N/A'
    
    if is_bentrok(form_data['hari'], form_data['jam_mulai'], form_data['jam_selesai'], ruangan, form_data['kelas'], form_data['dosen'], tipe_kelas):
        flash(f"Jadwal Bentrok! Ruangan, kelas, atau dosen sudah digunakan pada waktu tersebut.", "danger")
        return redirect(url_for('halaman_jadwal', action='new'))

    new_jadwal = Jadwal(
        nama_dosen=form_data['dosen'], mata_kuliah=form_data['matkul'], kelas=form_data['kelas'],
        hari=form_data['hari'], jam_mulai=form_data['jam_mulai'], jam_selesai=form_data['jam_selesai'],
        gedung=form_data.get('gedung') if tipe_kelas == 'Offline' else 'Online',
        lantai=form_data.get('lantai') if tipe_kelas == 'Offline' else 'N/A',
        ruangan=ruangan, tipe_kelas=tipe_kelas, user_id=current_user.id,
        sks=int(form_data.get('sks', 0))
    )
    db.session.add(new_jadwal)
    db.session.commit()
    flash('Booking berhasil disimpan!', 'success')
    return redirect(url_for('halaman_jadwal'))

@app.route('/ruangan_tersedia')
@login_required
def halaman_ruangan_tersedia():
    if current_user.role == 'mahasiswa':
        flash('Anda tidak memiliki hak akses untuk halaman ini.', 'warning')
        return redirect(url_for('halaman_jadwal'))
    
    selected_day = request.args.get('hari')
    room_availability_blocks = defaultdict(list)

    if selected_day:
        all_rooms_unfiltered = []
        for gedung_key, lantai_data in data_gedung.items():
            for lantai_key, rooms_list in lantai_data.items():
                all_rooms_unfiltered.extend(rooms_list)
        all_rooms = sorted(list(set(all_rooms_unfiltered)))
        
        existing_schedules = Jadwal.query.filter_by(hari=selected_day, tipe_kelas='Offline').all()
        
        time_slots = [(datetime.min + timedelta(minutes=15 * i)).time() for i in range(4 * 24)]
        
        booked_slots = defaultdict(set)
        for schedule in existing_schedules:
            start_dt = datetime.combine(datetime.min, parse_time(schedule.jam_mulai))
            end_dt = datetime.combine(datetime.min, parse_time(schedule.jam_selesai))
            current_dt = start_dt
            while current_dt < end_dt:
                booked_slots[current_dt.time()].add(schedule.ruangan)
                current_dt += timedelta(minutes=15)

        for room in all_rooms:
            start_block_time = time(7, 0)
            status = 'Tersedia' if room not in booked_slots.get(start_block_time, set()) else 'Terpakai'
            
            for t in time_slots[29:89]:
                new_status = 'Istirahat' if time(12, 0) <= t < time(13, 0) else ('Tersedia' if room not in booked_slots.get(t, set()) else 'Terpakai')
                if new_status != status:
                    end_block_time = t
                    room_availability_blocks[room].append({
                        'start': start_block_time.strftime('%H:%M'),
                        'end': end_block_time.strftime('%H:%M'),
                        'status': status
                    })
                    start_block_time = end_block_time
                    status = new_status
            
            room_availability_blocks[room].append({
                'start': start_block_time.strftime('%H:%M'),
                'end': time(22, 15).strftime('%H:%M'),
                'status': status
            })

    return render_template('ruangan_tersedia.html',
                           days=HARI_LIST,
                           selected_day=selected_day,
                           room_availability_blocks=room_availability_blocks)

# --- Rute Admin ---

@app.route('/generate_jadwal', methods=['GET', 'POST'])
@login_required
def halaman_generate():
    if current_user.role != 'admin':
        flash('Anda tidak memiliki hak akses untuk halaman ini.', 'danger')
        return redirect(url_for('halaman_jadwal'))

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('Tidak ada file yang dipilih.', 'warning')
            return redirect(request.url)

        try:
            print("[DEBUG] Membaca file...")
            df = pd.read_excel(file) if file.filename.endswith('.xlsx') else pd.read_csv(file)
            df.columns = [col.strip().upper() for col in df.columns]
            print(f"[DEBUG] Kolom terdeteksi: {list(df.columns)}")

            required_columns = {'MATA KULIAH', 'SKS', 'KELAS', 'DOSEN PENGAJAR'}
            if not required_columns.issubset(df.columns):
                missing_cols = required_columns - set(df.columns)
                flash(f"File tidak valid. Kolom berikut tidak ditemukan: {', '.join(missing_cols)}", 'danger')
                return redirect(request.url)

            # Pre-processing data
            cols_to_ffill = ['DOSEN PENGAJAR', 'MATA KULIAH', 'SKS', 'SMT', 'KELAS', 'DOSEN_HARI_KAMPUS', 'DOSEN_JAM_KAMPUS', 'TIPE_KELAS']
            for col in cols_to_ffill:
                if col in df.columns:
                    df[col] = df[col].ffill()

            df['SKS'] = pd.to_numeric(df['SKS'], errors='coerce').fillna(0).astype(int)
            df = df.sort_values(by='SKS', ascending=False).reset_index(drop=True)
            print(f"[DEBUG] File berhasil dibaca dan diproses. Total {len(df)} baris data.")

            # Cache jadwal yang sudah ada untuk performa
            all_existing_schedules = Jadwal.query.all()
            existing_schedules_cache = {
                'ruangan': defaultdict(lambda: defaultdict(list)),
                'kelas': defaultdict(lambda: defaultdict(list)),
                'dosen': defaultdict(lambda: defaultdict(list))
            }
            for sch in all_existing_schedules:
                existing_schedules_cache['ruangan'][sch.hari][sch.ruangan].append(sch)
                existing_schedules_cache['kelas'][sch.hari][sch.kelas].append(sch)
                existing_schedules_cache['dosen'][sch.hari][sch.nama_dosen].append(sch)

            new_schedules_to_add = []
            failed_to_schedule = []

            time_profiles = {
                'reguler': {'days': ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat'], 'start_hour': 8, 'end_hour': 18},
                'malam': {'days': ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat'], 'start_hour': 18, 'end_hour': 22}
            }

            # Pre-generate daftar ruangan
            all_available_rooms = []
            for gedung, lantai_data in data_gedung.items():
                for lantai, rooms in lantai_data.items():
                    all_available_rooms.extend(rooms)
            all_available_rooms = [r for r in all_available_rooms if r not in EXCLUDED_LAB_ROOMS_FOR_GENERATION]


            # Proses setiap baris di file
            for idx, row in df.iterrows():
                kelas_str = str(row.get('KELAS', '')).strip().upper()
                nama_dosen_str = str(row.get('DOSEN PENGAJAR', '')).strip()
                mata_kuliah_str = str(row.get('MATA KULIAH', '')).strip()
                tipe_kelas_str = str(row.get('TIPE_KELAS', 'OFFLINE')).strip().title()
                sks_val = int(row.get('SKS', 0))
                duration_minutes = sks_val * 50

                if not all([kelas_str, nama_dosen_str, mata_kuliah_str, sks_val > 0]):
                    failed_to_schedule.append({'course': f"{mata_kuliah_str} ({kelas_str})", 'reason': 'Data tidak lengkap (Dosen/Matkul/Kelas/SKS)'})
                    continue

                profile = time_profiles['malam'] if kelas_str.endswith('M') else time_profiles['reguler']
                slot_found = False

                for day in profile['days']:
                    if slot_found: break
                    
                    current_start_dt = datetime.strptime(f"{profile['start_hour']}:00", "%H:%M")
                    end_of_day_dt = datetime.strptime(f"{profile['end_hour']}:00", "%H:%M")

                    while current_start_dt < end_of_day_dt:
                        end_time_dt = current_start_dt + timedelta(minutes=duration_minutes)
                        
                        if end_time_dt > end_of_day_dt: break

                        if (current_start_dt.time() < time(13,0) and end_time_dt.time() > time(12,0)):
                            current_start_dt = datetime.strptime("13:00", "%H:%M")
                            continue

                        mulai_baru_time = current_start_dt.time()
                        selesai_baru_time = end_time_dt.time()

                        if tipe_kelas_str == 'Online':
                            if not is_bentrok_cached(day, mulai_baru_time, selesai_baru_time, 'N/A', kelas_str, nama_dosen_str, 'Online', existing_schedules_cache):
                                new_jadwal = Jadwal(nama_dosen=nama_dosen_str, mata_kuliah=mata_kuliah_str, kelas=kelas_str, hari=day, jam_mulai=mulai_baru_time.strftime("%H:%M"), jam_selesai=selesai_baru_time.strftime("%H:%M"), gedung='Online', lantai='N/A', ruangan='Online', tipe_kelas='Online', user_id=current_user.id, sks=sks_val)
                                new_schedules_to_add.append(new_jadwal)
                                existing_schedules_cache['kelas'][day][kelas_str].append(new_jadwal)
                                existing_schedules_cache['dosen'][day][nama_dosen_str].append(new_jadwal)
                                slot_found = True
                                break
                        else: # Offline
                            for room in all_available_rooms:
                                if not is_bentrok_cached(day, mulai_baru_time, selesai_baru_time, room, kelas_str, nama_dosen_str, 'Offline', existing_schedules_cache):
                                    gedung, lantai = next(((g, l) for g, l_data in data_gedung.items() for l, r_list in l_data.items() if room in r_list), ('N/A', 'N/A'))
                                    new_jadwal = Jadwal(nama_dosen=nama_dosen_str, mata_kuliah=mata_kuliah_str, kelas=kelas_str, hari=day, jam_mulai=mulai_baru_time.strftime("%H:%M"), jam_selesai=selesai_baru_time.strftime("%H:%M"), gedung=gedung, lantai=lantai, ruangan=room, tipe_kelas='Offline', user_id=current_user.id, sks=sks_val)
                                    new_schedules_to_add.append(new_jadwal)
                                    existing_schedules_cache['ruangan'][day][room].append(new_jadwal)
                                    existing_schedules_cache['kelas'][day][kelas_str].append(new_jadwal)
                                    existing_schedules_cache['dosen'][day][nama_dosen_str].append(new_jadwal)
                                    slot_found = True
                                    break
                        
                        if slot_found: break
                        current_start_dt += timedelta(minutes=15)

                if not slot_found:
                    failed_to_schedule.append({'course': f"{mata_kuliah_str} ({kelas_str})", 'reason': 'Tidak ada slot waktu tersedia'})

            if new_schedules_to_add:
                db.session.add_all(new_schedules_to_add)
                db.session.commit()
                flash(f"Generate Selesai! {len(new_schedules_to_add)} jadwal berhasil dibuat.", 'success')
            
            if failed_to_schedule:
                flash(f"{len(failed_to_schedule)} mata kuliah gagal dijadwalkan.", 'warning')
                for item in failed_to_schedule:
                    flash(f"- {item['course']}: {item['reason']}", 'secondary')

            return redirect(url_for('halaman_jadwal'))

        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Terjadi error saat generate jadwal: {e}")
            flash(f"Terjadi error saat memproses file: {e}", 'danger')
            return redirect(request.url)

    return render_template('generate_jadwal.html')


@app.route('/generate_progress')
@login_required
def get_generate_progress():
    return jsonify(generate_progress_status)

@app.route('/download_template')
@login_required
def download_template():
    output = io.BytesIO()
    df_template = pd.DataFrame(columns=['KODE', 'DOSEN PENGAJAR', 'MATA KULIAH', 'SMT', 'SKS', 'KELAS', 'DOSEN_HARI_KAMPUS', 'DOSEN_JAM_KAMPUS', 'TIPE_KELAS'])
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_template.to_excel(writer, index=False, sheet_name='Sheet1')
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', download_name='template_generate_jadwal.xlsx', as_attachment=True)

@app.route('/download_excel')
@login_required
def download_excel():
    query = Jadwal.query
    jadwal_data = query.order_by(Jadwal.hari, Jadwal.jam_mulai).all()
    df_export = pd.DataFrame([(d.id, d.nama_dosen, d.mata_kuliah, d.sks, d.kelas, d.hari, d.jam_mulai, d.jam_selesai, d.gedung, d.lantai, d.ruangan, d.tipe_kelas) for d in jadwal_data],
                             columns=["ID", "Dosen", "Matkul", "SKS", "Kelas", "Hari", "Mulai", "Selesai", "Gedung", "Lantai", "Ruangan", "Tipe"])
    output = io.BytesIO()
    df_export.to_excel(output, index=False, sheet_name='Jadwal')
    output.seek(0)
    return send_file(output, as_attachment=True, download_name='Jadwal_Lengkap.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/delete_jadwal/<int:jadwal_id>', methods=['POST'])
@login_required
def delete_jadwal(jadwal_id):
    if current_user.role != 'admin':
        flash('Aksi tidak diizinkan.', 'danger')
        return redirect(url_for('halaman_jadwal'))
    jadwal_to_delete = Jadwal.query.get_or_404(jadwal_id)
    db.session.delete(jadwal_to_delete)
    db.session.commit()
    flash('Jadwal berhasil dihapus.', 'success')
    return redirect(url_for('halaman_jadwal'))

@app.route('/delete_all_schedules', methods=['POST'])
@login_required
def delete_all_schedules():
    if current_user.role != 'admin':
        flash('Aksi tidak diizinkan.', 'danger')
        return redirect(url_for('halaman_jadwal'))
    try:
        num_deleted = db.session.query(Jadwal).delete()
        db.session.commit()
        flash(f'{num_deleted} jadwal berhasil dihapus.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Terjadi error saat menghapus semua jadwal: {e}', 'danger')
    return redirect(url_for('halaman_jadwal'))

# --- Konteks Prosesor & Inisialisasi DB ---
@app.context_processor
def inject_data():
    return dict(data_gedung=data_gedung)

def init_database():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            hashed_password = bcrypt.generate_password_hash('admin').decode('utf-8')
            admin_user = User(username='admin', password=hashed_password, role='admin')
            db.session.add(admin_user)
            db.session.commit()

if __name__ == '__main__':
       
    with app.app_context():
        if not os.path.exists(db_path):
            init_database()
        else: # Pastikan tabel terbaru dibuat jika db sudah ada
            db.create_all()

    app.run(debug=True)
