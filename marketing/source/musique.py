"""Musique de fond originale de la publicite BALLAN, generee par code.

Libre de droits par construction : aucune piece existante n'est utilisee.
Calee sur le montage de pub.html (40 s) :

    0-5 s    accroche        nappe et arpege, sans batterie
    5-34 s   scenes          groove complet ; plus d'elan des 26 s (rendez-vous)
    34-40 s  ecran de fin    cadence sur re majeur, puis fondu

Re majeur, 96 BPM (une mesure = 2,5 s), progression I-V-vi-IV.
Les sons de notification tombent sur l'apparition des bulles de pub.html.

    python3 musique.py sortie.wav
"""

from __future__ import annotations

import sys
import wave

import numpy as np

SR = 44_100
DUREE = 40.0
MESURE = 2.5  # 96 BPM, 4 temps
TEMPS = MESURE / 4
N = int(SR * DUREE)

rng = np.random.default_rng(2026)  # deterministe : meme fichier a chaque rendu


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


# Accords (midi) : D, A, Bm, G — basse, puis notes de la nappe.
ACCORDS = [
    (38, [62, 66, 69]),  # D
    (45, [57, 61, 64]),  # A
    (47, [59, 62, 66]),  # Bm
    (43, [55, 59, 62]),  # G
]

gauche = np.zeros(N)
droite = np.zeros(N)


def poser(signal: np.ndarray, debut: float, gain: float = 1.0, pan: float = 0.0) -> None:
    """Ajoute un son mono a l'instant donne, panoramique -1 (gauche) a +1 (droite)."""
    i = int(debut * SR)
    if i >= N:
        return
    s = signal[: N - i] * gain
    gauche[i : i + len(s)] += s * np.sqrt((1 - pan) / 2)
    droite[i : i + len(s)] += s * np.sqrt((1 + pan) / 2)


def t_(duree: float) -> np.ndarray:
    return np.arange(int(duree * SR)) / SR


# -- instruments -----------------------------------------------------


def marimba(midi: float, duree: float = 0.9) -> np.ndarray:
    t = t_(duree)
    f = hz(midi)
    corps = np.sin(2 * np.pi * f * t) * np.exp(-t * 5.5)
    attaque = 0.35 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t * 28)
    son = corps + attaque
    son[: int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))
    return son


def nappe(notes: list[int], duree: float, desaccord: float) -> np.ndarray:
    t = t_(duree)
    son = np.zeros_like(t)
    for m in notes:
        f = hz(m) * 2 ** (desaccord / 1200)
        son += np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)
        son += 0.12 * np.sin(2 * np.pi * 3 * f * t)
    env = np.minimum(1, t / 0.35) * np.minimum(1, (duree - t) / 0.4)
    return son * np.clip(env, 0, 1) / len(notes)


def basse(midi: int, duree: float) -> np.ndarray:
    t = t_(duree)
    f = hz(midi)
    # Fondamentale + octave : la fondamentale reste audible sur un haut-parleur de telephone.
    son = np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * 2 * f * t)
    son += 0.15 * np.sin(2 * np.pi * 3 * f * t)
    env = np.minimum(1, t / 0.01) * np.exp(-t * 1.6)
    return son * env


def grosse_caisse() -> np.ndarray:
    t = t_(0.35)
    f = 50 + 90 * np.exp(-t * 30)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(phase) * np.exp(-t * 9)


def claquement() -> np.ndarray:
    t = t_(0.25)
    bruit = rng.standard_normal(len(t))
    bruit = bruit - np.convolve(bruit, np.ones(6) / 6, mode="same")  # passe-haut grossier
    corps = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30)
    return (0.6 * bruit * np.exp(-t * 18) + 0.4 * corps) * 0.8


def charleston() -> np.ndarray:
    t = t_(0.08)
    bruit = rng.standard_normal(len(t))
    bruit = np.diff(bruit, prepend=0)
    return bruit * np.exp(-t * 60) * 0.35


def notification(entrant: bool) -> np.ndarray:
    if entrant:  # deux notes montantes, la5 puis re6
        a, b = marimba(81, 0.5), marimba(86, 0.6)
        son = np.zeros(int(0.75 * SR))
        son[: len(a)] += a
        decal = int(0.09 * SR)
        son[decal : decal + len(b)] += b
        return son
    t = t_(0.18)  # envoi : petit « pop » descendant
    f = 1100 * np.exp(-t * 8)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 25)


# -- arrangement -----------------------------------------------------

FIN_GROOVE = 34.0
DEBUT_GROOVE = 5.0
ELAN = 26.0

nb_mesures = int(np.ceil(FIN_GROOVE / MESURE))
for b in range(nb_mesures):
    debut = b * MESURE
    note_basse, notes = ACCORDS[b % 4]
    duree = min(MESURE, FIN_GROOVE - debut)

    # Nappe, legerement differente a gauche et a droite pour l'espace.
    poser(nappe(notes, duree + 0.3, -4), debut, 0.16, -0.6)
    poser(nappe(notes, duree + 0.3, +4), debut, 0.16, +0.6)

    # Arpege de marimba en croches.
    motif = [notes[0], notes[1], notes[2], notes[0] + 12, notes[2], notes[1], notes[0] + 12, notes[2]]
    for k, m in enumerate(motif):
        t0 = debut + k * TEMPS / 2
        if t0 >= FIN_GROOVE:
            break
        gain = 0.16 if t0 < DEBUT_GROOVE else 0.22
        poser(marimba(m + 12), t0, gain, pan=0.3 if k % 2 else -0.3)
        if t0 >= ELAN:  # plus d'elan : doublure a l'octave
            poser(marimba(m + 24, 0.5), t0, 0.07, pan=-0.5 if k % 2 else 0.5)

    if debut + 0.01 < DEBUT_GROOVE:
        continue

    # Basse sur les temps 1 et 3, et la croche avant le 3.
    for offset in (0, 1.5 * TEMPS, 2 * TEMPS):
        if debut + offset < FIN_GROOVE:
            poser(basse(note_basse, 1.0), debut + offset, 0.30)

    # Batterie legere.
    for temps in range(4):
        t0 = debut + temps * TEMPS
        if t0 >= FIN_GROOVE:
            break
        if temps in (0, 2):
            poser(grosse_caisse(), t0, 0.55)
        if temps in (1, 3):
            poser(claquement(), t0, 0.22, pan=0.1)
        poser(charleston(), t0 + TEMPS / 2, 0.5, pan=0.4)
        if t0 >= ELAN:
            poser(charleston(), t0, 0.3, pan=-0.4)

# Montee vers l'entree du groove (souffle de bruit filtre, 4 -> 5 s).
t = t_(1.0)
souffle = np.diff(rng.standard_normal(len(t)), prepend=0) * (t / 1.0) ** 2 * 0.12
poser(souffle, DEBUT_GROOVE - 1.0, 1.0)

# Ecran de fin : accord de re tenu, re grave, et une derniere phrase de marimba.
poser(nappe([62, 66, 69, 74], DUREE - FIN_GROOVE, -4), FIN_GROOVE, 0.24, -0.6)
poser(nappe([62, 66, 69, 74], DUREE - FIN_GROOVE, +4), FIN_GROOVE, 0.24, +0.6)
poser(basse(38, 3.0), FIN_GROOVE, 0.35)
poser(grosse_caisse(), FIN_GROOVE, 0.6)
for k, m in enumerate([74, 78, 81, 86]):
    poser(marimba(m, 1.6), FIN_GROOVE + 0.2 + k * TEMPS / 2, 0.22, pan=-0.3 + 0.2 * k)

# Notifications, sur l'apparition des bulles (pub.html).
for t0 in (6.5, 13.4, 20.4, 26.5, 29.8):
    poser(notification(True), t0, 0.30, pan=0.15)
for t0 in (8.8, 15.9, 22.9, 28.4):
    poser(notification(False), t0, 0.22, pan=-0.15)

# -- mastering simple ------------------------------------------------

stereo = np.stack([gauche, droite], axis=1)
temps_abs = np.arange(N) / SR
fondu = np.minimum(1, temps_abs / 0.8) * np.clip((DUREE - temps_abs) / 2.5, 0, 1)
stereo *= fondu[:, None]
stereo = np.tanh(stereo * 1.2) / np.tanh(1.2)  # saturation douce, pas d'ecretage dur
stereo *= 0.89 / np.max(np.abs(stereo))  # crete a -1 dBFS

sortie = sys.argv[1] if len(sys.argv) > 1 else "musique.wav"
with wave.open(sortie, "wb") as f:
    f.setnchannels(2)
    f.setsampwidth(2)
    f.setframerate(SR)
    f.writeframes((stereo * 32767).astype("<i2").tobytes())
print(f"{sortie} : {DUREE:.0f} s, {SR} Hz, stereo")
