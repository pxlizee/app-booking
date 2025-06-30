import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'proyek-final-ini-sudah-selesai-dan-bekerja')
    
    # Path ke file database SQLite di dalam folder 'instance'
    db_path = os.path.join(os.path.abspath(os.path.dirname(__name__)), 'instance', 'database.db')
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False