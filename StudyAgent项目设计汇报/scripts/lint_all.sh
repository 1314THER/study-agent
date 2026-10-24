#!/bin/zsh
SP=/Users/sqz/.workbuddy/binaries/node/versions/22.22.2-6/bin/slidep
DIR="/Users/sqz/Desktop/study-agent/StudyAgent项目设计汇报"
PPTX="$DIR/StudyAgent项目设计汇报.pptx"
cd "$DIR" || exit 1
for i in $(seq 1 124); do
  f=$(printf "slides/%03d.slide" "$i")
  idx=$((i - 1))
  out=$($SP lint "$PPTX" --dsl-file "$f" --page-index "$idx" 2>&1 | grep '"ok"' | head -1)
  echo "$i $out"
done
echo "LINT_DONE"
