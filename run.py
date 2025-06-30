from app import create_app, db
from app.models import User, Gedung, Lantai, Ruangan
from app import bcrypt # Menggunakan bcrypt dari __init__.py

# Membuat instance aplikasi menggunakan App Factory
app = create_app()

def setup_database(app):
    """Fungsi untuk inisialisasi database dan data awal."""
    with app.app_context():
        # Membuat semua tabel
        db.create_all()

        # Tambah user admin jika belum ada
        if not User.query.filter_by(username='admin').first():
            hashed_password = bcrypt.generate_password_hash('admin').decode('utf-8')
            admin_user = User(username='admin', password=hashed_password, role='admin')
            db.session.add(admin_user)
            print("User 'admin' berhasil dibuat.")

        # Tambah data gedung, lantai, dan ruangan awal jika belum ada
        if not Gedung.query.first():
            print("Membuat data gedung, lantai, dan ruangan awal...")
            # Data awal (yang sebelumnya hard-coded)
            data_gedung_awal = {
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
            kategori_lab = {
                "Lab Komputer Mesin 1", "Lab Komputer Mesin 2",
                "Lab Komputer Hardware", "Lab Komputer Software",
                "Lab Komputer DKV 1", "Lab Komputer DKV 2",
                "Lab Teknik Sipil", "Lab Teknik Elektro"
            }

            for nama_gedung, lantai_data in data_gedung_awal.items():
                gedung_obj = Gedung(nama_gedung=nama_gedung)
                db.session.add(gedung_obj)
                db.session.flush()

                for nama_lantai, ruangan_list in lantai_data.items():
                    lantai_obj = Lantai(nama_lantai=nama_lantai, gedung_id=gedung_obj.id)
                    db.session.add(lantai_obj)
                    db.session.flush()

                    for nama_ruangan in ruangan_list:
                        kategori = "Lab" if nama_ruangan in kategori_lab else "Kelas"
                        ruangan_obj = Ruangan(
                            nama_ruangan=nama_ruangan,
                            kategori=kategori,
                            lantai_id=lantai_obj.id
                        )
                        db.session.add(ruangan_obj)
            
            db.session.commit()
            print("Data awal berhasil dimasukkan ke database.")
        else:
            print("Database sudah berisi data.")


if __name__ == '__main__':
    setup_database(app)
    app.run(debug=True)