#!/bin/zsh
# 逐页写入 PPTX（带重试）
SP=/Users/sqz/.workbuddy/binaries/node/versions/22.22.2-6/bin/slidep
DIR="/Users/sqz/Desktop/study-agent/StudyAgent项目设计汇报"
PPTX="$DIR/StudyAgent项目设计汇报.pptx"
cd "$DIR" || exit 1
for i in $(seq 1 124); do
  f=$(printf "slides/%03d.slide" "$i")
  for attempt in 1 2 3; do
    out=$($SP upsert-dsl "$PPTX" --dsl-file "$f" 2>&1 | grep '"ok"' | head -1)
    if [[ "$out" == *'"ok":true'* ]]; then break; fi
    sleep 3
  done
  echo "$i $out"
done
echo "ALL_DONE"
