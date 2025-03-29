from flask import Flask
from .routes import humidity_bp


def create_app():
    app = Flask(__name__)
    app.config.from_pyfile('../config.py')

    # Регистрация Blueprint
    app.register_blueprint(humidity_bp)

    return app