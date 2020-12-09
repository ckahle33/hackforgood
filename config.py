import os
from dotenv import load_dotenv
basedir = os.path.abspath(os.path.dirname(__file__))

load_dotenv()

class Config(object):
    # GCP
    DB_USER=os.getenv("DB_USER")
    DB_PASSWORD=os.getenv("DB_PASS")
    DB_DATABASE=os.getenv("DB_NAME")
    DB_CONNECTION_NAME = os.getenv("DB_CONNECTION")
    LOCAL_SQLALCHEMY_DATABASE_URI = (
        'postgresql+psycopg2://{nam}:{pas}@127.0.0.1:5432/{dbn}').format (
        nam=DB_USER,
        pas=DB_PASSWORD,
        dbn=DB_DATABASE,
    )

    LIVE_SQLALCHEMY_DATABASE_URI = (
        'postgresql+psycopg2://{nam}:{pas}@localhost/{dbn}?host=/cloudsql/{con}').format (
        nam=DB_USER,
        pas=DB_PASSWORD,
        dbn=DB_DATABASE,
        con=DB_CONNECTION_NAME,
    )

    if os.getenv('GAE_INSTANCE'):
        SQLALCHEMY_DATABASE_URI = LIVE_SQLALCHEMY_DATABASE_URI
    else:
        SQLALCHEMY_DATABASE_URI = LOCAL_SQLALCHEMY_DATABASE_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False

