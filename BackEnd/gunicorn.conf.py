"""gunicorn 설정.

SQLite 를 쓰므로 워커를 늘리기보다 스레드로 동시성을 확보한다.
(250명 규모에서는 이 정도면 충분하고, 파일 락 충돌도 피할 수 있다)
"""

import os

# 포트는 APP_PORT 하나로 정한다. docker-compose 의 ports·healthcheck 와
# 반드시 같은 값이어야 하므로, 여기저기 하드코딩하지 않는다.
bind = os.getenv("GUNICORN_BIND") or f"0.0.0.0:{os.getenv('APP_PORT', '8000')}"
workers = int(os.getenv("GUNICORN_WORKERS", "1"))
threads = int(os.getenv("GUNICORN_THREADS", "8"))
worker_class = "gthread"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
# 조회 요청의 쿼리스트링/본문은 남기지 않는다 (개인정보)
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms'
