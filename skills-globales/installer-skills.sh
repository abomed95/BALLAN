#!/usr/bin/env bash
# Installe find-skills, arena et harvey-sales pour Claude Code (niveau utilisateur, tous projets).
# Usage : placer ce script a cote de arena.zip et harvey-sales.zip, puis : bash installer-skills.sh
set -euo pipefail
cd "$(dirname "$0")"
DEST="$HOME/.claude/skills"; mkdir -p "$DEST"
echo "1/3 find-skills"; npx -y skills add https://github.com/vercel-labs/skills --skill find-skills -g -y
for s in arena harvey-sales; do
  echo "-> $s"; rm -rf "$DEST/$s"; unzip -q -o "$s.zip" -d "$DEST"
done
echo "Installe dans $DEST :"; ls "$DEST"
