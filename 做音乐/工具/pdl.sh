#!/bin/bash
# 多连接分段下载: pdl <url> <输出文件> <连接数>
pdl() {
  local url="$1" out="$2" parts="${3:-8}"
  local size=$(curl -sIL -A "Mozilla/5.0" "$url" | grep -i '^content-length' | tail -1 | tr -d '\r' | awk '{print $2}')
  if [ -z "$size" ] || [ "$size" -lt 1000000 ]; then echo "ERROR: size=$size"; return 1; fi
  echo "[$(date +%T)] $out 开始下载 size=$size parts=$parts"
  local chunk=$(( (size + parts - 1) / parts ))
  for i in $(seq 0 $((parts-1))); do
    local start=$((i*chunk)); local end=$(( (i+1)*chunk - 1 )); [ $end -ge $size ] && end=$((size-1))
    curl -sL --retry 5 --retry-all-errors -A "Mozilla/5.0" -r "$start-$end" -o "$out.part$i" "$url" &
  done
  wait
  local got=0
  for i in $(seq 0 $((parts-1))); do [ -f "$out.part$i" ] || { echo "ERROR: part$i 缺失"; return 1; }; done
  cat $(for i in $(seq 0 $((parts-1))); do echo "$out.part$i"; done) > "$out"
  rm -f "$out".part*
  got=$(stat -c %s "$out")
  if [ "$got" = "$size" ]; then echo "[$(date +%T)] $out 完成 $(du -m "$out" | cut -f1)MB"
  else echo "ERROR: $out 大小不符 got=$got want=$size"; return 1; fi
}
