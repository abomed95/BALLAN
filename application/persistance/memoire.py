"""Pendants memoire des adaptateurs qui n'ont pas d'equivalent dans le domaine."""

from __future__ import annotations

import threading


class DedoublonnageMemoire:
    def __init__(self) -> None:
        self._vus: set[str] = set()
        self._verrou = threading.Lock()

    def premiere_reception(self, message_id: str) -> bool:
        with self._verrou:
            if message_id in self._vus:
                return False
            self._vus.add(message_id)
            return True

    def sante(self) -> bool:
        return True
