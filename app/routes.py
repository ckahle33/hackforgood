from app import app, db
from app.models import User, Project, Organization, Tag
from flask import render_template, url_for, session

from authlib.integrations.flask_client import OAuth
import os

oauth = OAuth(app)
github = oauth.register(
    name='github',
    authorize_url='https://github.com/login/oauth/authorize',
    access_token_url='https://github.com/login/oauth/access_token',
    client_id=os.getenv('GITHUB_CLIENT_ID'),
    client_secret=os.getenv('GITHUB_CLIENT_SECRET'),
    api_base_url='https://api.github.com'
)

@app.cli.command('seed')

def seed():
    project = Project(name="Test Project", description="Test description.....", image_url="https://source.unsplash.com/random")
    db.session.add(project)
    org = Organization(name="Test Org", description="Test description.....", image_url="https://source.unsplash.com/random")
    db.session.add(org)
    db.session.commit()

@app.route('/')
@app.route('/index')
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

@app.route('/projects')
def projects():
    projects = Project.query.all()
    if len(projects) != 0:
        return render_template('projects.html', projects=projects)
    else:
        return render_template('projects.html', projects={title:"test", description:"test description"})

@app.route('/organizations')
def organizations():
    orgs=Organization.query.all()
    return render_template('organizations.html', orgs=orgs)

@app.route('/developers')
def developers():
    return render_template('developers.html')

@app.route('/tags')
def tags():
    tags = Tag.query.all()
    return render_template('tags.html', tags=tags)

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
