#!/usr/bin/env bash
# 개발용 위임 토큰 서명 키(ES256)를 infra/dev-keys/에 만듭니다. 이 폴더는 커밋하지 않습니다.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p infra/dev-keys
if [ -f infra/dev-keys/delegation-es256.pem ]; then
  echo "이미 있습니다: infra/dev-keys/delegation-es256.pem"
  exit 0
fi
openssl ecparam -name prime256v1 -genkey -noout -out infra/dev-keys/delegation-es256.pem
openssl ec -in infra/dev-keys/delegation-es256.pem -pubout -out infra/dev-keys/delegation-es256.pub.pem 2>/dev/null
chmod 600 infra/dev-keys/delegation-es256.pem
echo "만들었습니다: infra/dev-keys/delegation-es256.pem"
