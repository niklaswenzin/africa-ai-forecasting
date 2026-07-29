"""pruefung.py

Plausibilitaetspruefung fuer Prognosen: passt die Zahl zur Begruendung?

Der Anlass
----------
Bei der Frage "Will Israel be found guilty in South Africa's genocide case by
the ICJ before 2027?" lieferte gpt-5.6-luna:

    probability : 0.995
    reasoning   : "... making a merits finding before January 1, 2027
                   extraordinarily unlikely."

Die Begruendung war sachlich richtig und schloss sogar die naheliegende
Verwechslung (vorsorgliche Massnahmen als Schuldspruch) ausdruecklich aus.
Nur die Zahl war die Gegenwahrscheinlichkeit: das Modell schrieb P(Nein) in
das Feld fuer P(Ja). Kein Parsing-Fehler - der Wert kam so aus dem Modell.

Ein solcher Fehler ist besonders tueckisch, weil er unauffaellig ist: eine
Prognose von 0.995 sieht nach hoher Sicherheit aus, nicht nach einem Fehler.
Auf der Seite stand er als groesste Abweichung ganz oben, und im Brier Score
haette er als schwerer Irrtum gezaehlt, obwohl das Modell richtig gedacht hat.

Wie geprueft wird
-----------------
Nur bei Extremwerten, also unter EXTREM_UNTEN oder ueber EXTREM_OBEN. Dazwischen
ist eine Begruendung fast immer mit beiden Richtungen vereinbar, und jede
Pruefung produzierte mehr Fehlalarme als Treffer.

Gesucht wird nach Wendungen, die der Zahl klar widersprechen: bei einer hohen
Wahrscheinlichkeit Formulierungen der Unwahrscheinlichkeit, bei einer niedrigen
solche der Gewissheit. Bewusst mehrwortige, eindeutige Wendungen - ein blosses
"not" kaeme in fast jeder Begruendung vor und waere als Signal wertlos.

Was die Pruefung NICHT tut
--------------------------
Sie dreht die Zahl nicht um. Aus "die Begruendung klingt gegenteilig" folgt
nicht, dass 1 minus p richtig waere - vielleicht ist auch die Begruendung
schief. Der Aufrufer fragt stattdessen genau einmal neu, wie schon bei
ungueltigem JSON. Bleibt der Widerspruch, wird die Prognose behalten und
markiert, nicht stillschweigend korrigiert oder verworfen.
"""

# Ab wo eine Prognose als extrem gilt.
EXTREM_UNTEN = 0.02
EXTREM_OBEN = 0.98

# Wendungen, die einer HOHEN Wahrscheinlichkeit widersprechen. Alles in
# Kleinschreibung; der Vergleichstext wird ebenfalls klein gemacht.
GEGEN_HOCH = (
    "unlikely",
    "improbable",
    "impossible",
    "not expected",
    "no realistic",
    "will not",
    "would not",
    "won't",
    "does not satisfy",
    "did not find",
    "fails to meet",
    "cannot be met",
    "extremely low",
    "very low probability",
    "no indication",
    "premature",
)

# Wendungen, die einer NIEDRIGEN Wahrscheinlichkeit widersprechen.
GEGEN_NIEDRIG = (
    "highly likely",
    "very likely",
    "virtually certain",
    "almost certain",
    "all but certain",
    "has already won",
    "already been declared",
    "is set to",
    "will almost surely",
    "overwhelming majority",
    "practically guaranteed",
)


# Fragen, die nach dem AUSBLEIBEN eines Ereignisses fragen. Bei ihnen dreht
# sich die Polaritaet um, und die Wortpruefung wird unbrauchbar.
#
# Realer Fehlalarm: "Will there be NO Somaliland parliamentary election before
# 2027?" mit p=0.98 und der Begruendung "a snap election appears unlikely".
# Die Begruendung stuetzt die hohe Zahl - unwahrscheinlich ist die Wahl,
# gefragt ist aber nach ihrem Ausbleiben. Lexikalisch ist das nicht sauber
# aufzuloesen, darum pruefen wir solche Fragen gar nicht erst.
#
# Das kostet Abdeckung: eine echte Verwechslung in einer negativ gestellten
# Frage entgeht uns. Ein falsches "unplausibel" auf einer richtigen Prognose
# waere aber schaedlicher - es stuende als Warnung auf der Karte und wuerde
# einen korrekten Wert in Zweifel ziehen.
NEGIERTE_FRAGE = (
    " no ",
    "there be no",
    " not ",
    "fail to",
    "fails to",
    " without ",
    " cease ",
    " out as ",
)


def ist_extrem(probability):
    """True, wenn die Zahl im Bereich liegt, den wir gegenpruefen."""
    return probability <= EXTREM_UNTEN or probability >= EXTREM_OBEN


def ist_negativ_gestellt(frage):
    """True, wenn die Frage nach dem Ausbleiben eines Ereignisses fragt."""
    if not frage:
        return False
    text = f" {frage.lower()} "
    return any(wendung in text for wendung in NEGIERTE_FRAGE)


def finde_widerspruch(probability, reasoning, frage=""):
    """Gibt die widersprechende Wendung zurueck, oder None.

    None heisst "kein Widerspruch gefunden" - nicht "die Prognose ist
    richtig". Die Pruefung ist ein Netz mit grossen Maschen, kein Beweis.

    Negativ gestellte Fragen werden uebersprungen, siehe NEGIERTE_FRAGE.
    """
    if probability is None or not reasoning:
        return None
    if not ist_extrem(probability):
        return None
    if ist_negativ_gestellt(frage):
        return None

    text = reasoning.lower()

    if probability >= EXTREM_OBEN:
        kandidaten = GEGEN_HOCH
    else:
        kandidaten = GEGEN_NIEDRIG

    for wendung in kandidaten:
        if wendung in text:
            return wendung

    return None


def beschreibe(probability, wendung):
    """Formuliert die Warnung fuer die Konsole."""
    richtung = "hoch" if probability >= EXTREM_OBEN else "niedrig"
    return (f"Zahl {probability} ist extrem {richtung}, die Begruendung "
            f"enthaelt aber \"{wendung}\"")
