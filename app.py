from flask import Flask
from flask import render_template
app = Flask(__name__)

@app.route('/')
def index():
        return render_template('index.html')

@app.route('/onboarding')
def onboarding():
        return render_template('onboarding.html')

@app.route('/login')
def login():
        return render_template('login.html')
