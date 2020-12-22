from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os, logging, pdb

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
app.config.from_object(Config)
app.logger.setLevel(logging.INFO)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

from app import routes, models, auth
