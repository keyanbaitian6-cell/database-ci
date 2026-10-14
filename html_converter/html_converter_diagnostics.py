"""Small local logs of processing stages; never dump HTML, Cookies or headers."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER = logging.getLogger('database.html_converter')
LOG_PATH = Path(__file__).parent / 'data' / 'logs' / 'diagnostics.log'


def setup():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=1024 * 1024, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.info('app started; diagnostics revision 20261015-1')
    return LOG_PATH
