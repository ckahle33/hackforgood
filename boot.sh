#! /bin/sh

# curl -O https://www.python.org/ftp/python/3.9.0/python-3.9.0-macosx10.9.pkg
# sudo installer -pkg python-3.9.0-macosx10.9.pkg
python3 -m venv venv # creates a directory in ./ where all modules live
source venv/bin/activate # activate the virtural environment
pip install -r requirements.txt # grabs modules
psql -c 'CREATE DATABASE hackforgood'
echo -e "DATABASE_URI='postgres://postgres@localhost/hackforgood'" >> .env2
export FLASK_APP=app.py
flask db upgrade
flask seed
flask run
