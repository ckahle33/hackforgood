from flask import Flask
from flask import render_template, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from authlib.integrations.flask_client import OAuth
import os, logging, pdb

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.logger.setLevel(logging.INFO)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI')
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# to go into models file
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    auth_token = db.Column(db.String(120), unique=True, nullable=True)
    avatar_url = db.Column(db.String(200), unique=True, nullable=True)
    location = db.Column(db.String(200), unique=False, nullable=True)


oauth = OAuth(app)
github = oauth.register(
    name='github',
    authorize_url='https://github.com/login/oauth/authorize',
    access_token_url='https://github.com/login/oauth/access_token',
    client_id=os.getenv('CLIENT_ID'),
    client_secret=os.getenv('CLIENT_SECRET'),
    api_base_url='https://api.github.com'
)

@app.route('/')
def index():
    if session.get('username') is not None:
        user = User.query.filter_by(username=session.get('username')).first()
        return render_template('index.html', user=user)
    else:
        return render_template('index.html')


@app.route('/onboarding')
def onboarding():
    return render_template('onboarding.html')

@app.route('/login')
def login():
    redirect_uri = url_for('authorize', _external=True)
    return github.authorize_redirect(redirect_uri)

@app.route('/authorize')
def authorize():
    token = github.authorize_access_token()
    # you can save the token into database
    resp = oauth.github.get('user', token=token)
    profile = resp.json()
    if not User.query.filter_by(username=profile['login']):
        user = User(username=profile['login'],
                    email=profile['email'],
                    auth_token=token['access_token'],
                    avatar_url=profile['avatar_url'],
                    location=profile['location'])
        db.session.add(user)
        db.session.commit()
    session["username"] = profile['login']
    return render_template('index.html')

@app.route('/github')
def show_github_profile():
    resp = oauth.github.get('user')
    profile = resp.json()
    return render_template('github.html', profile=profile)