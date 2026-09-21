FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    TZ=Asia/Seoul

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# chmod 를 반드시 함께 한다.
# COPY 는 빌드 컨텍스트의 모드 비트를 그대로 가져오는데, 시놀로지 공유폴더처럼
# ACL 을 쓰는 곳에서 올린 파일은 POSIX 모드가 000 으로 보이는 경우가 있다.
# 그러면 chown 으로 소유자를 바꿔도 읽기 비트가 없어 실행이 불가능하다.
#   PermissionError: [Errno 13] Permission denied: '/app/gunicorn.conf.py'
# a+rX = 모두에게 읽기, 디렉터리(및 이미 실행 가능한 파일)에만 실행 권한.
RUN mkdir -p /data && \
    adduser --disabled-password --gecos "" --uid 1000 appuser && \
    chmod -R a+rX /app && \
    chown -R appuser:appuser /app /data
USER appuser

VOLUME ["/data"]

# 실제 포트는 APP_PORT 로 정한다 (docker-compose 에서 주입).
# EXPOSE 는 문서 역할이라 기본값만 적어 둔다.
EXPOSE 5055

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,sys,urllib.request; p=os.getenv('APP_PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health', timeout=3).status==200 else 1)"

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
