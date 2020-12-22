import os
from dotenv import load_dotenv
basedir = os.path.abspath(os.path.dirname(__file__))

load_dotenv()

class Config(object):
    # GCP
    DB_USER=os.getenv("DB_USER")
    DB_PASSWORD=os.getenv("DB_PASS")
    DB_DATABASE=os.getenv("DB_NAME")
    DB_CONNECTION = os.getenv("DB_CONNECTION")
    LOCAL_SQLALCHEMY_DATABASE_URI = (
        'postgresql+psycopg2://{db_user}:{db_password}@127.0.0.1:5432/{db_name}').format (
        db_user=DB_USER,
        db_password=DB_PASSWORD,
        db_name=DB_DATABASE,
    )

    LIVE_SQLALCHEMY_DATABASE_URI = (
        'postgresql+psycopg2://{db_user}:{db_password}@localhost/{db_name}?host=/cloudsql/{db_conn}').format (
        db_user=DB_USER,
        db_password=DB_PASSWORD,
        db_name=DB_DATABASE,
        db_conn=DB_CONNECTION,
    )

    if os.getenv('GAE_INSTANCE') == None:
        SQLALCHEMY_DATABASE_URI = LOCAL_SQLALCHEMY_DATABASE_URI
    else:
        SQLALCHEMY_DATABASE_URI = LIVE_SQLALCHEMY_DATABASE_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False

