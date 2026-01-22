from datetime import datetime
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from .config import Config
from models import db, User, UserState, UserRole

login_manager = LoginManager()
migrate = Migrate()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Logga in for att komma at denna sida.'


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

        with app.app_context():
        db.create_all()


    # Initialize Flask-Mail if configured
    if app.config.get('MAIL_SERVER'):
        from flask_mail import Mail
        mail = Mail(app)
        app.extensions['mail'] = mail

    # User loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from blueprints.main import main_bp
    from blueprints.auth import auth_bp
    from blueprints.events import events_bp
    from blueprints.stories import stories_bp
    from blueprints.gallery import gallery_bp
    from blueprints.profile import profile_bp
    from blueprints.admin import admin_bp
    from blueprints.strava import strava_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(events_bp, url_prefix='/events')
    app.register_blueprint(stories_bp, url_prefix='/stories')
    app.register_blueprint(gallery_bp, url_prefix='/gallery')
    app.register_blueprint(profile_bp, url_prefix='/profile')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(strava_bp, url_prefix='/strava')

    # Create default admin user if not exists (runs after migrations)
    @app.cli.command('create-admin')
    def create_admin():
        """Create the default admin user."""
        if not User.query.filter_by(username='klubban').first():
            admin = User(
                username='klubban',
                email='klubban@klubbansvanners.se',
                display_name='Klubban',
                bio='Mystisk. Legendarisk. Alltid framfor dig i backen.',
                is_admin=True,
                state=UserState.ACTIVE.value,
                role=UserRole.ADMIN.value,
                email_verified_at=datetime.utcnow(),
                leaderboard_opt_in=True
            )
            admin.set_password('klubban2026')
            db.session.add(admin)
            db.session.commit()
            print('Admin user created: klubban')
        else:
            print('Admin user already exists')

    return app
