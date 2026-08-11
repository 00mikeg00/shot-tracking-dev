import os
import logging
from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_login import LoginManager
from dotenv import load_dotenv

from app.config import MAX_CONTENT_LENGTH, UPLOAD_FOLDER
from app.database.db import close_db
from app.models.user_model import User

# Blueprints
from app.routes.main_routes import main_bp
from app.routes.auth_routes import auth_bp
from app.routes.admin_routes import admin_bp
from app.routes.assignments_routes import assignments_bp
from app.routes.classes_routes import classes_bp
from app.routes.films_routes import films_bp
from app.routes.film_config_routes import film_config_bp
from app.routes.users_routes import users_bp
from app.routes.workflow_routes import workflow_routes
from app.routes.video_routes import video_bp
from app.routes.review_routes import review_routes
from app.routes.semester_routes import semesters_bp
from app.routes.dashboard_routes import dashboard_bp
from app.routes.help_routes import help_bp
from app.routes.scene_pipeline_routes import scene_pipeline_bp
from app.routes.bugreport_routes import bugreport_bp
from app.routes.assignment_config_routes import config_bp
from app.routes.launcher_routes import launcher_bp
from app.routes.capstone_routes import capstone_bp
from app.routes.planning_routes import planning_bp
from app.routes.video_reference_routes import video_reference_bp
from app.routes.xsheet_routes import xsheet_bp

login_manager = LoginManager()
login_manager.login_view = "auth.login"


def create_app(config_override=None):
    load_dotenv()

    from app import config
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static"
    )

    CORS(
    app,
    supports_credentials=True,
    origins=["http://localhost:3000"]
)

    app.config.from_object(config_override or config)

    app.secret_key = os.getenv("SECRET_KEY", "fallback_secret_key")

    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    app.logger.setLevel(logging.INFO)

    # Register Blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(assignments_bp, url_prefix='/assignments')
    app.register_blueprint(classes_bp, url_prefix='/classes')
    app.register_blueprint(films_bp, url_prefix='/films')
    app.register_blueprint(film_config_bp, url_prefix="/films/config")
    app.register_blueprint(users_bp, url_prefix='/users')
    app.register_blueprint(workflow_routes, url_prefix='/workflow')
    app.register_blueprint(video_bp, url_prefix='/video')
    app.register_blueprint(review_routes, url_prefix='/review')
    app.register_blueprint(semesters_bp, url_prefix='/semesters')
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(help_bp)
    app.register_blueprint(scene_pipeline_bp)
    app.register_blueprint(bugreport_bp)
    app.register_blueprint(config_bp, url_prefix='/classes')
    app.register_blueprint(launcher_bp)
    app.register_blueprint(capstone_bp)
    app.register_blueprint(planning_bp)
    app.register_blueprint(video_reference_bp)
    app.register_blueprint(xsheet_bp)

    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.get_by_id(int(user_id))

    @app.context_processor
    def inject_app_metadata():
        return {
            "APP_NAME": app.config.get("APP_NAME", "App Name"),
            "APP_VERSION": app.config.get("APP_VERSION", "0.0.0"),
            "APP_YEAR": app.config.get("APP_YEAR", "2025-6"),
            "APP_COPYRIGHT": app.config.get("APP_COPYRIGHT", "© UC")
        }

    # -------------------------------
    # Markup React App Route (Next export)
    # -------------------------------

    @app.route("/markup")
    def serve_markup():
        static_dir = os.path.join(os.path.dirname(__file__), "..", "static", "react")
        return send_from_directory(static_dir, "markup.html")


    @app.route("/markup/_next/static/<path:path>")
    def serve_next_static(path):
        static_dir = os.path.join(os.path.dirname(__file__), "..", "static", "react", "_next", "static")
        return send_from_directory(static_dir, path)


    @app.route("/markup/_next/<path:path>")
    def serve_next_assets(path):
        static_dir = os.path.join(os.path.dirname(__file__), "..", "static", "react", "_next")
        return send_from_directory(static_dir, path)


    @app.route("/markup/<path:path>")
    def serve_markup_assets(path):
        static_dir = os.path.join(os.path.dirname(__file__), "..", "static", "react")
        return send_from_directory(static_dir, path)


    @app.route("/static/<path:path>")
    def serve_static_assets(path):
        static_dir = os.path.join(os.path.dirname(__file__), "..", "static", "react", "static")
        return send_from_directory(static_dir, path)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)