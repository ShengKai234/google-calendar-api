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

## Hardware
### Raspberry Pi
- Raspberry Pi 4 Model B Rev 1.5 8GB
- MicroSD Card (64GB)

### E-Paper
- [7.3inch e-Paper HAT (F)](https://www.waveshare.net/shop/7.3inch-e-Paper-HAT-F.htm)
- Python Tool
    ```shell
    sudo apt install -y swig libgpiod-dev liblgpio-dev python3-lgpio
    pip install lgpio Pillow

    # test example
    python3 /e-paper/RaspberryPi_JetsonNano/examples/epd_7in3e_test.py
    ```

## Install OS
- Raspberry Pi OS Lite (64-bit)
## 