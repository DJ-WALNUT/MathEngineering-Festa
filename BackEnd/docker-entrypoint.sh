#!/bin/sh
# 컨테이너 진입점.
#
# /data 는 컨테이너 밖(NAS 공유폴더)을 붙인 것이라 소유자가 root 나 DSM 사용자로
# 잡혀 있기 일쑤다. 그 상태로 uid 1000(appuser) 이 DB 파일을 만들려 하면
#   sqlite3.OperationalError: unable to open database file
# 로 워커가 뜨지 못한다.
#
# 그래서 root 로 시작해 소유자를 맞추고 appuser 로 내려간다. 다만 시놀로지
# 공유폴더는 Windows ACL 을 쓰기 때문에 **chown 이 되어도 ACL 이 uid 1000 의
# 쓰기를 열어 주지 않을 수 있다.** 그때는 권한을 내리지 않고 root 로 띄운다 —
# 소규모 내부 서비스에서 '안 뜨는 것'보다 나쁜 일은 없다. 어느 쪽으로 갔는지는
# 로그 첫 줄에 남긴다.
set -e

DATA_DIR="${DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA_DIR"
  chown -R appuser:appuser "$DATA_DIR" 2>/dev/null || echo "[entrypoint] $DATA_DIR 소유자 변경 실패 (읽기 전용이거나 ACL 볼륨)"
  chmod -R u+rwX,g+rwX "$DATA_DIR" 2>/dev/null || true

  # appuser 로 실제 파일을 하나 써 본다. 모드 비트만 보고 판단하면 ACL 볼륨에서 틀린다.
  if setpriv --reuid=appuser --regid=appuser --init-groups \
       sh -c "touch '$DATA_DIR/.write-test' && rm -f '$DATA_DIR/.write-test'" 2>/dev/null; then
    echo "[entrypoint] $DATA_DIR 쓰기 확인 — appuser(uid 1000) 로 실행합니다."
    exec setpriv --reuid=appuser --regid=appuser --init-groups "$@"
  fi

  echo "[entrypoint] 경고: $DATA_DIR 에 appuser 가 쓸 수 없어 root 로 실행합니다." \
       "($(stat -c '모드 %A 소유자 %u:%g' "$DATA_DIR" 2>/dev/null || echo '상태 확인 불가'))" \
       "NAS 에서 'sudo chown -R 1000:1000 <볼륨경로>' 를 하면 다음 기동부터 권한을 내립니다."
fi

exec "$@"
