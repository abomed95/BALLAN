#!/bin/sh
# Sauvegarde quotidienne de la base BALLAN, au format pg_dump personnalise.
# Garde 14 jours dans /sauvegardes (monte depuis ./sauvegardes sur l'hote).
# Restauration : voir docs/DEPLOIEMENT.md.
set -u
DOSSIER=/sauvegardes
while true; do
    FICHIER="$DOSSIER/ballan-$(date +%Y%m%d-%H%M).dump"
    if pg_dump -h postgres -U ballan -d ballan -Fc -f "$FICHIER"; then
        echo "sauvegarde ok : $FICHIER"
        find "$DOSSIER" -maxdepth 1 -name 'ballan-*.dump' -mtime +14 -exec rm -f {} \;
    else
        echo "ECHEC de la sauvegarde" >&2
    fi
    sleep 86400
done
