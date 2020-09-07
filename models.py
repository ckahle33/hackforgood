# from app import db
#
# db = SQLAlchemy(app)
#
# class User(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     username = db.Column(db.String(80), unique=True, nullable=False)
#     email = db.Column(db.String(120), unique=True, nullable=False)
#     auth_token = db.Column(db.String(120), unique=True, nullable=True)
#     avatar_url = db.Column(db.String(200), unique=True, nullable=True)
#     location = db.Column(db.String(200), unique=False, nullable=True)
