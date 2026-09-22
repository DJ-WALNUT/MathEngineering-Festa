#!/bin/sh
# 컨테이너 진입점.
#
# /data 는 컨테이너 밖(NAS 공유폴더)을 붙인 것이라 소유자가 root 나 DSM 사용자로
# 잡혀 있기 일쑤다. 그 상태로 uid 1000(appuser) 이 DB 파일을 만들려 하면
#   sqlite3.OperationalError: unable to open database file
# 로 워커가 뜨지 못한다. SSH 로 들어가 chown 을 치게 두는 대신, 처음에 잠깐 root 로
# 폴더 소유자를 맞추고 **곧바로 appuser 로 내려가서** 앱을 띄운다.
set -e

DATA_DIR="${DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  # 볼륨이 읽기 전용이거나 NFS 라 chown 이 막힐 수 있다. 그때는 그대로 넘어가고
  # 아래 앱 기동에서 무엇이 문제인지 한국어로 알려 준다.
  chown -R appuser:appuser "$DATA_DIR" 2>/dev/null || true
  exec setpriv --reuid=appuser --regid=appuser --init-groups "$@"
fi

exec "$@"
