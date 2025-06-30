import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager

# Inisialisasi ekstensi
db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'routes.login'
login_manager.login_message_category = 'info'
login_manager.login_message = 'Silakan login untuk mengakses halaman ini.'

def create_app():
    """Membuat dan mengkonfigurasi instance aplikasi Flask."""
    app = Flask(__name__, instance_relative_config=True)

    # Memuat konfigurasi
    app.config.from_object('app.config.Config')

    # Memastikan folder instance ada
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Mengaitkan ekstensi dengan aplikasi
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    
    with app.app_context():
        # Import rute
        from . import routes
        app.register_blueprint(routes.bp)
        
        # Import model agar bisa diakses
        from . import models

        return app