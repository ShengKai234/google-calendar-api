Python 3.11.2
env - virtualenv
  # Use default python version
  virtualenv venv

  # venv setting env name
  # use 3.11.2
  virtualenv -p ~/.pyenv/versions/3.11.2/bin/python venv
Entry virtual env
  source venv/bin/activate	
exist virtual env
  deactivate
Export requirements
  pip freeze > requirements.txt
Install requirements
  pip install -r requirements.txt	
Freeze maintance
  pip install -r requirements-to-freeze.txt --upgrade
  pip freeze > requirements.txt