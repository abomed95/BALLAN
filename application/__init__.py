"""Couche application de BALLAN : ce qui assemble le domaine et le rend utilisable.

    core/          noyau metier (creneaux, calendrier, i18n)       - Python pur
    verticals/     regles scolaires (familles, rendez-vous)        - Python pur
    application/   cas d'usage et adaptateurs                      - ce paquet
        conversation/  agent conversationnel (machine a etats)
        persistance/   adaptateurs PostgreSQL
        whatsapp/      canal WhatsApp Cloud API
        api/           application HTTP (webhook, secretariat)
        conteneur.py   racine de composition : qui parle a qui

Le sens des dependances est unique : ``application`` importe ``core`` et
``verticals``, jamais l'inverse. Le domaine se teste sans base ni reseau.
"""
