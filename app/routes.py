
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

def is_bentrok(hari, mulai_baru, selesai_baru, ruangan_id, kelas, nama_dosen_baru, tipe_kelas, jadwal_id_to_ignore=None):
    mulai_baru_time = parse_time(mulai_baru)
    selesai_baru_time = parse_time(selesai_baru)
    if not (mulai_baru_time and selesai_baru_time):
        return False

    query = Jadwal.query.filter(
        Jadwal.hari == hari,
        db.func.time(Jadwal.jam_selesai) > mulai_baru_time,
        db.func.time(Jadwal.jam_mulai) < selesai_baru_time
    )

    # Jika sedang mengedit, abaikan jadwal dengan ID ini
    if jadwal_id_to_ignore:
        query = query.filter(Jadwal.id != jadwal_id_to_ignore)

    conflicting_schedules = query.all()
    
    # (Sisa logika pengecekan bentrok sama seperti sebelumnya...)
    for sched in conflicting_schedules:
        # ... (pengecekan bentrok ruangan, kelas, dosen) ...
        # (tidak ada perubahan di sini)
        if tipe_kelas == 'Offline' and sched.tipe_kelas == 'Offline' and sched.ruangan_id == int(ruangan_id):
            flash(f"Jadwal bentrok: Ruangan sudah dipakai.", "danger")
            return True
        if sched.kelas == kelas:
            flash(f"Jadwal bentrok: Kelas sudah ada jadwal lain.", "danger")
            return True
        if sched.nama_dosen == nama_dosen_baru:
            flash(f"Jadwal bentrok: Dosen sudah mengajar.", "danger")
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
def is_bentrok_cache(hari, mulai_baru_time, selesai_baru_time, ruangan_id, kelas, nama_dosen, cache):
    # Cek bentrok ruangan (hanya jika kelas Offline)
    if ruangan_id:
        for jadwal_ada in cache['ruangan'].get(hari, {}).get(ruangan_id, []):
            mulai_ada = parse_time(jadwal_ada.jam_mulai)
            selesai_ada = parse_time(jadwal_ada.jam_selesai)
            if mulai_ada < selesai_baru_time and selesai_ada > mulai_baru_time:
                return True # Bentrok ruangan

    # Cek bentrok kelas
    for jadwal_ada in cache['kelas'].get(hari, {}).get(kelas, []):
        mulai_ada = parse_time(jadwal_ada.jam_mulai)
        selesai_ada = parse_time(jadwal_ada.jam_selesai)
        if mulai_ada < selesai_baru_time and selesai_ada > mulai_baru_time:
            return True # Bentrok kelas

    # Cek bentrok dosen
    for jadwal_ada in cache['dosen'].get(hari, {}).get(nama_dosen, []):
        mulai_ada = parse_time(jadwal_ada.jam_mulai)
        selesai_ada = parse_time(jadwal_ada.jam_selesai)
        if mulai_ada < selesai_baru_time and selesai_ada > mulai_baru_time:
            return True # Bentrok dosen
            
    return False
# Hapus fungsi start_generation yang lama, dan ganti dengan ini:
@bp.route('/generate/start', methods=['POST'])
@login_required


def start_generation():
    if current_user.role != 'admin':
        flash("Hanya admin yang dapat mengakses fitur ini.", "danger")
        return redirect(url_for('routes.landing_page'))

    file = request.files.get('file')
    if not file or file.filename == '':
        flash('Tidak ada file yang dipilih.', 'warning')
        return redirect(url_for('routes.halaman_generate'))

    try:
        df = pd.read_excel(file) if file.filename.endswith('.xlsx') else pd.read_csv(file)
        df.columns = [col.strip().upper() for col in df.columns]
        required_columns = ['MATA KULIAH', 'SKS', 'KELAS', 'DOSEN PENGAJAR']
        if not all(col in df.columns for col in required_columns):
            flash(f"File harus memiliki kolom: {', '.join(required_columns)}", 'danger')
            return redirect(url_for('routes.halaman_generate'))

        # 1. PRE-FETCH DATA UNTUK EFISIENSI
        # Ambil semua jadwal yang ada dari DB
        all_existing_schedules = Jadwal.query.all()
        # Ambil semua ruangan kelas dari DB
        all_available_rooms = Ruangan.query.filter(Ruangan.kategori == 'Kelas').all()

        # Buat cache untuk pengecekan bentrok yang cepat
        existing_schedules_cache = {
            'ruangan': defaultdict(lambda: defaultdict(list)),
            'kelas': defaultdict(lambda: defaultdict(list)),
            'dosen': defaultdict(lambda: defaultdict(list))
        }
        for sch in all_existing_schedules:
            if sch.ruangan_id:
                existing_schedules_cache['ruangan'][sch.hari][sch.ruangan_id].append(sch)
            existing_schedules_cache['kelas'][sch.hari][sch.kelas].append(sch)
            existing_schedules_cache['dosen'][sch.hari][sch.nama_dosen].append(sch)
        
        # 2. PERSIAPAN LOOPING
        new_schedules_to_add = []
        failed_to_schedule = []
        hari_kerja = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat']
        jam_mulai_kerja = time(8, 0)
        jam_selesai_kerja = time(18, 0)
        jam_istirahat_mulai = time(12, 0)
        jam_istirahat_selesai = time(13, 0)

        # 3. PROSES GENERATE JADWAL
        for index, row in df.iterrows():
            # Konversi SKS ke durasi menit
            try:
                sks = int(row['SKS'])
                duration_minutes = sks * 50
            except (ValueError, TypeError):
                failed_to_schedule.append(f"{row['MATA KULIAH']} ({row['KELAS']}) - SKS tidak valid")
                continue

            slot_ditemukan = False
            # Loop setiap hari kerja
            for hari in hari_kerja:
                if slot_ditemukan: break
                
                # Loop setiap ruangan yang tersedia
                for ruangan in all_available_rooms:
                    if slot_ditemukan: break
                    
                    # Loop setiap 15 menit dari jam mulai sampai jam selesai kerja
                    current_time_slot = datetime.combine(datetime.today(), jam_mulai_kerja)
                    while current_time_slot.time() < jam_selesai_kerja:
                        
                        # Lewati jam istirahat
                        if jam_istirahat_mulai <= current_time_slot.time() < jam_istirahat_selesai:
                            current_time_slot = datetime.combine(datetime.today(), jam_istirahat_selesai)
                            continue

                        mulai_baru = current_time_slot.time()
                        selesai_baru_dt = current_time_slot + timedelta(minutes=duration_minutes)
                        selesai_baru = selesai_baru_dt.time()

                        # Jika jadwal melewati jam kerja, hentikan loop waktu untuk hari ini
                        if selesai_baru > jam_selesai_kerja or selesai_baru_dt.day > current_time_slot.day:
                            break
                        
                        # Cek bentrok dengan jadwal yang sudah ada (di DB dan di cache sesi ini)
                        if not is_bentrok_cache(hari, mulai_baru, selesai_baru, ruangan.id, row['KELAS'], row['DOSEN PENGAJAR'], existing_schedules_cache):
                            # Slot ditemukan!
                            new_jadwal = Jadwal(
                                nama_dosen=row['DOSEN PENGAJAR'],
                                mata_kuliah=row['MATA KULIAH'],
                                sks=sks,
                                kelas=row['KELAS'],
                                hari=hari,
                                jam_mulai=mulai_baru.strftime('%H:%M'),
                                jam_selesai=selesai_baru.strftime('%H:%M'),
                                tipe_kelas='Offline',
                                ruangan_id=ruangan.id,
                                user_id=current_user.id
                            )
                            new_schedules_to_add.append(new_jadwal)

                            # Perbarui cache agar jadwal berikutnya tidak bentrok dengan yang ini
                            existing_schedules_cache['ruangan'][hari][ruangan.id].append(new_jadwal)
                            existing_schedules_cache['kelas'][hari][row['KELAS']].append(new_jadwal)
                            existing_schedules_cache['dosen'][hari][row['DOSEN PENGAJAR']].append(new_jadwal)
                            
                            slot_ditemukan = True
                            break # Hentikan loop waktu, lanjut ke matkul berikutnya

                        # Lanjut ke slot waktu berikutnya (15 menit)
                        current_time_slot += timedelta(minutes=15)

            if not slot_ditemukan:
                failed_to_schedule.append(f"{row['MATA KULIAH']} ({row['KELAS']}) - Tidak ada slot tersedia")
        
        # 4. SIMPAN KE DATABASE
        if new_schedules_to_add:
            db.session.add_all(new_schedules_to_add)
            db.session.commit()
            flash(f"Generate Selesai! {len(new_schedules_to_add)} jadwal berhasil dibuat.", 'success')

        if failed_to_schedule:
            flash(f"{len(failed_to_schedule)} mata kuliah gagal dijadwalkan. Silakan periksa bentrok atau coba lagi.", 'warning')
            for item in failed_to_schedule[:5]: # Tampilkan 5 error pertama
                flash(item, 'secondary')

        return redirect(url_for('routes.halaman_jadwal'))

    except Exception as e:
        db.session.rollback()
        flash(f"Terjadi error saat proses generate: {e}", "danger")
        return redirect(url_for('routes.halaman_generate'))


# Pastikan fungsi halaman_import Anda terlihat seperti ini
# Ganti fungsi halaman_import yang lama dengan versi baru yang lebih informatif ini
@bp.route('/import', methods=['GET', 'POST'])
@login_required
def halaman_import():
    if current_user.role != 'admin':
        flash("Hanya admin yang bisa mengakses halaman ini.", "danger")
        return redirect(url_for('routes.landing_page'))

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('Tidak ada file yang dipilih.', 'warning'); return redirect(request.url)

        try:
            df = pd.read_excel(file) if file.filename.endswith('.xlsx') else pd.read_csv(file)
            required_columns = ['Nama Dosen', 'Mata Kuliah', 'SKS', 'Kelas', 'Hari', 'Jam Mulai', 'Jam Selesai', 'Tipe Kelas']
            if not all(col in df.columns for col in required_columns):
                flash(f"File harus memiliki kolom: {', '.join(required_columns)}", 'danger'); return redirect(request.url)

            all_existing_schedules = Jadwal.query.all()
            existing_schedules_cache = defaultdict(lambda: defaultdict(list))
            for sch in all_existing_schedules:
                if sch.ruangan_id: existing_schedules_cache['ruangan'][sch.hari][sch.ruangan_id].append(sch)
                existing_schedules_cache['kelas'][sch.hari][sch.kelas].append(sch)
                existing_schedules_cache['dosen'][sch.hari][sch.nama_dosen].append(sch)

            jadwal_ditambahkan = []
            error_details = [] # List untuk menyimpan detail error

            for index, row in df.iterrows():
                baris_ke = index + 2 # Nomor baris di Excel (header di baris 1)
                mulai_time = parse_time(row['Jam Mulai'])
                selesai_time = parse_time(row['Jam Selesai'])

                if not (mulai_time and selesai_time):
                    error_details.append(f"Baris {baris_ke}: Format 'Jam Mulai' atau 'Jam Selesai' salah.")
                    continue

                ruangan_id = None
                if row['Tipe Kelas'].strip().lower() == 'offline':
                    nama_ruangan_excel = row.get('Ruangan')
                    if not isinstance(nama_ruangan_excel, str) or not nama_ruangan_excel.strip():
                        error_details.append(f"Baris {baris_ke}: Kolom 'Ruangan' kosong untuk kelas Offline.")
                        continue
                    
                    ruangan = Ruangan.query.filter_by(nama_ruangan=nama_ruangan_excel.strip()).first()
                    if ruangan:
                        ruangan_id = ruangan.id
                    else:
                        error_details.append(f"Baris {baris_ke}: Ruangan '{nama_ruangan_excel}' tidak ditemukan di database.")
                        continue
                
                if not is_bentrok_cache(row['Hari'], mulai_time, selesai_time, ruangan_id, row['Kelas'], row['Nama Dosen'], existing_schedules_cache):
                    # (Logika menambahkan jadwal sama seperti sebelumnya)
                    new_jadwal = Jadwal(nama_dosen=row['Nama Dosen'], mata_kuliah=row['Mata Kuliah'], sks=int(row['SKS']), kelas=row['Kelas'], hari=row['Hari'], jam_mulai=mulai_time.strftime('%H:%M'), jam_selesai=selesai_time.strftime('%H:%M'), tipe_kelas=row['Tipe Kelas'], ruangan_id=ruangan_id, user_id=current_user.id)
                    jadwal_ditambahkan.append(new_jadwal)
                    if ruangan_id: existing_schedules_cache['ruangan'][new_jadwal.hari][ruangan_id].append(new_jadwal)
                    existing_schedules_cache['kelas'][new_jadwal.hari][new_jadwal.kelas].append(new_jadwal)
                    existing_schedules_cache['dosen'][new_jadwal.hari][new_jadwal.nama_dosen].append(new_jadwal)
                else:
                    error_details.append(f"Baris {baris_ke}: Jadwal untuk kelas '{row['Kelas']}' bentrok.")

            if jadwal_ditambahkan:
                db.session.add_all(jadwal_ditambahkan)
                db.session.commit()
            
            flash(f"Import selesai! {len(jadwal_ditambahkan)} jadwal berhasil ditambahkan.", 'success')
            if error_details:
                gagal_count = len(error_details)
                flash(f"{gagal_count} jadwal gagal diimpor. Lihat detail di bawah:", 'warning')
                for error in error_details[:5]: # Tampilkan 5 error pertama
                    flash(error, 'secondary')

        except Exception as e:
            db.session.rollback()
            flash(f"Terjadi error saat memproses file: {e}", 'danger')
        
        return redirect(url_for('routes.halaman_jadwal'))
        
    return render_template('import_jadwal.html')

@bp.route('/download/template_generate')
@login_required
def download_template():
    if current_user.role != 'admin':
        flash("Hanya admin yang bisa mengakses fitur ini.", "danger")
        return redirect(url_for('routes.landing_page'))

    # Membuat file Excel di memori
    output = io.BytesIO()

    # Membuat DataFrame kosong dengan header yang dibutuhkan
    df_template = pd.DataFrame(columns=[
        'KODE',
        'DOSEN PENGAJAR',
        'MATA KULIAH',
        'SMT',
        'SKS',
        'KELAS',
        'DOSEN_HARI_KAMPUS',
        'DOSEN_JAM_KAMPUS',
        'TIPE_KELAS'
    ])
    
    # Menulis DataFrame ke file Excel di memori
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_template.to_excel(writer, index=False, sheet_name='Template')
    
    output.seek(0)
    
    # Mengirim file ke browser pengguna untuk diunduh
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='template_generate_jadwal.xlsx'
    )
    
# Tambahkan fungsi baru ini di app/routes.py
@bp.route('/download/template_import')
@login_required
def download_template_import():
    if current_user.role != 'admin':
        return redirect(url_for('routes.landing_page'))

    output = io.BytesIO()

    # Membuat DataFrame dengan kolom sesuai permintaan Anda
    df_template = pd.DataFrame(columns=[
        'No',
        'Nama Dosen',
        'Mata Kuliah',
        'Semester',
        'SKS',
        'Kelas',
        'Hari',
        'Jam Mulai', # Dipecah dari kolom "Jam"
        'Jam Selesai',# Dipecah dari kolom "Jam"
        'Tipe Kelas', # Diperlukan oleh sistem
        'Ruangan'     # Diperlukan untuk kelas Offline
    ])
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_template.to_excel(writer, index=False, sheet_name='Template Import')
    
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='template_import_jadwal.xlsx'
    )
    
@bp.route('/jadwal/edit/<int:jadwal_id>', methods=['GET'])
@login_required
def edit_jadwal(jadwal_id):
    if current_user.role != 'admin':
        flash("Hanya admin yang dapat mengakses halaman ini.", "danger")
        return redirect(url_for('routes.halaman_jadwal'))

    # Ambil data jadwal dari database
    jadwal = Jadwal.query.get_or_404(jadwal_id)

    # Siapkan data untuk dioper ke formulir
    form_data = {
        'nama_dosen': jadwal.nama_dosen,
        'mata_kuliah': jadwal.mata_kuliah,
        'sks': jadwal.sks,
        'kelas': jadwal.kelas,
        'hari': jadwal.hari,
        'jam_mulai': jadwal.jam_mulai,
        'jam_selesai': jadwal.jam_selesai,
        'tipe_kelas': jadwal.tipe_kelas,
        'ruangan': jadwal.ruangan_id,
        'lantai': jadwal.ruangan_obj.lantai_id if jadwal.ruangan_obj else None,
        'gedung': jadwal.ruangan_obj.lantai.gedung_id if jadwal.ruangan_obj else None,
    }

    # Render template booking, tapi dalam mode edit
    return render_template('booking_form.html', edit_mode=True, jadwal_id=jadwal.id, form_data=form_data)


@bp.route('/jadwal/update/<int:jadwal_id>', methods=['POST'])
@login_required
def update_jadwal(jadwal_id):
    if current_user.role != 'admin':
        return redirect(url_for('routes.landing_page'))

    # Ambil jadwal yang akan diupdate dari DB
    jadwal_to_update = Jadwal.query.get_or_404(jadwal_id)
    form = request.form
    
    # Cek bentrok, tapi abaikan jadwal saat ini (dengan ID-nya)
    ruangan_id = form.get('ruangan') if form.get('tipe_kelas') == 'Offline' else None
    if is_bentrok(form.get('hari'), form.get('jam_mulai'), form.get('jam_selesai'), ruangan_id, form.get('kelas'), form.get('dosen'), form.get('tipe_kelas'), jadwal_id_to_ignore=jadwal_id):
        return redirect(url_for('routes.edit_jadwal', jadwal_id=jadwal_id))

    # Update data di object jadwal
    jadwal_to_update.nama_dosen = form.get('dosen')
    jadwal_to_update.mata_kuliah = form.get('matkul')
    jadwal_to_update.sks = int(form.get('sks', 0))
    jadwal_to_update.kelas = form.get('kelas')
    jadwal_to_update.hari = form.get('hari')
    jadwal_to_update.jam_mulai = form.get('jam_mulai')
    jadwal_to_update.jam_selesai = form.get('jam_selesai')
    jadwal_to_update.tipe_kelas = form.get('tipe_kelas')
    jadwal_to_update.ruangan_id = ruangan_id

    # Simpan perubahan ke database
    db.session.commit()
    flash('Jadwal berhasil diperbarui!', 'success')
    return redirect(url_for('routes.halaman_jadwal'))