# elread

Python3 modules for elevation logger.

## Scripts
- `elread.py` : for logging.
- `eldata.py` : for reading log file.
- `z_enable.py` : for enabling detection of Z(reset) signal. (We should enable for elevation calibration.)
- `z_disable.py` : for disabling detection of Z(reset) signal. (We should disable for observation.)
- `el_server.py` : script for server side for reading recent angle.
  - We should be running if we want use `el_client.py`
    - for example : `gb@dodo:~/logger$ python3 -m elread.el_server` in screen.
- `el_client.py` : for reading recent angle value from log file if el_server is runing.
- `check_lock.sh` : for removing lock file.