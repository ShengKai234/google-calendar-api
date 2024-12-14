# Python 3.11.2
## env - virtualenv
  Use default python version
  ```shell  
  virtualenv venv
  # venv setting env name
  # use 3.11.2
  virtualenv -p ~/.pyenv/versions/3.11.2/bin/python venv
  ```

  Entry virtual env
  ```shell  
  source venv/bin/activate
  ```

  exist virtual env
  ```shell  
  deactivate
  ```

  Export requirements
  ```shell
  pip freeze > requirements.txt
  ```

  Install requirements
  ```shell
  pip install -r requirements.txt	
  ```
  
  Freeze maintance
  ```shell
  pip install -r requirements-to-freeze.txt --upgrade
  pip freeze > requirements.txt
  ```