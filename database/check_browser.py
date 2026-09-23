"""A local-only browser lifecycle diagnostic; never visits the data site."""
import json
import time
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

root=Path(__file__).parent
log=root/'browser-check.jsonl'
def record(**fields):
    with log.open('a',encoding='utf-8') as f:
        f.write(json.dumps(dict(time=datetime.now().isoformat(),**fields),ensure_ascii=False)+'\n')

driver=None
try:
    record(event='start')
    options=webdriver.ChromeOptions()
    options.add_argument('--window-size=900,600')
    driver=webdriver.Chrome(options=options,service=Service(log_output=str(root/'driver-check.log')))
    driver.get('data:text/html,<title>database browser check</title><h1>database</h1><p>Browser test. This window will close automatically.</p>')
    for i in range(6):
        record(event='alive',step=i,title=driver.title)
        time.sleep(5)
    record(event='success')
except Exception as e:
    record(event='error',kind=type(e).__name__,detail=str(e))
finally:
    if driver:
        try: driver.quit()
        except Exception: pass
