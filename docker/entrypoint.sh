#!/bin/sh
# Startskript des Containers.
#
# nexbeat soll nicht als Administrator laufen. Ein von aussen eingehaengtes
# Datenverzeichnis traegt aber die Rechte des Wirtssystems, und die passen selten
# zufaellig zum Benutzer im Abbild. Deshalb richtet der Container kurz als
# Administrator die Rechte ein und gibt danach an den Benutzer "nexbeat" ab.
# Welchem Benutzer des Wirts die Dateien gehoeren, sagen PUID und PGID.

set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Port im Container, Standard 8000. NEXBEAT_PORT braucht, wer im Host-Netzwerk
# betreibt: Dort ist der Port im Container der Port des Servers. In der JSON-Form
# von CMD ersetzt Docker keine Variablen, deshalb steht es hier. So weit oben, weil
# weiter unten ein Ausgang fuer unprivilegierte Starts kommt.
if [ "$1" = "uvicorn" ]; then
    case " $* " in
        *" --port "*) ;;
        *) set -- "$@" --port "${NEXBEAT_PORT:-8000}" ;;
    esac
fi

# Startet der Container schon ohne Administratorrechte ("user:" in der
# compose-Datei), gibt es nichts einzurichten.
if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

if [ "$(id -g nexbeat)" != "$PGID" ]; then
    groupmod -o -g "$PGID" nexbeat
fi
if [ "$(id -u nexbeat)" != "$PUID" ]; then
    usermod -o -u "$PUID" nexbeat
fi

mkdir -p /data

# Nur anfassen, wenn der Besitzer nicht stimmt. Ein "chown -R" bei jedem Start
# kostet bei grossen Verzeichnissen unnoetig Zeit.
if [ "$(stat -c %u /data)" != "$PUID" ] || [ "$(stat -c %g /data)" != "$PGID" ]; then
    echo "nexbeat: adjusting ownership of the data directory to $PUID:$PGID."
    chown -R "$PUID:$PGID" /data
fi

# ⚠️ Besitzer heisst nicht beschreibbar. Auf einem NAS kann das Verzeichnis dem
# richtigen Benutzer gehoeren und ueber Zugriffslisten trotzdem dicht sein. Dann
# kaeme mitten im Start ein langer Python-Fehler, aus dem niemand die Ursache
# liest. Deshalb wird hier wirklich geschrieben, als der Benutzer, der es spaeter tut.
if ! gosu nexbeat sh -c 'touch /data/.write-test' 2>/dev/null; then
    echo "nexbeat: the data directory is not writable." >&2
    echo "" >&2
    echo "  nexbeat runs as uid $PUID, gid $PGID and cannot write to the" >&2
    echo "  directory mounted at /data. Nothing has been started." >&2
    echo "" >&2
    echo "  On the host, that directory needs to belong to that user:" >&2
    echo "" >&2
    echo "      sudo chown -R $PUID:$PGID /path/to/your/data" >&2
    echo "      sudo chmod -R u+rwX /path/to/your/data" >&2
    echo "" >&2
    echo "  PUID and PGID are set in your compose file. To find your own," >&2
    echo "  run 'id' on the host and use the uid and gid it reports." >&2
    exit 1
fi
rm -f /data/.write-test

exec gosu nexbeat "$@"
