# Pubblicare Kerberus 0.9.0

La versione applicativa ha una sola sorgente in `kerberus/__init__.py`. Il metadata Python e l'installer la importano automaticamente. Per preparare una nuova release, aggiornare codice, documentazione e changelog con un solo comando:

```powershell
.\.venv\Scripts\python.exe bump_version.py 0.9.0
```

Il comando accetta versioni nel formato `MAJOR.MINOR.PATCH`, interrompe l'operazione prima di scrivere se i riferimenti non sono coerenti e aggiunge una sezione TODO in cima al changelog.

## Verifica locale

Dopo aver creato il commit candidato:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe build_source_release.py --tag v0.9.0
```

Per verificare anche i binari Windows servono Go 1.24+ e le dipendenze `.[build]`:

```powershell
.\.venv\Scripts\python.exe build_release.py
```

## Pubblicazione automatica

1. Assicurarsi che tutte le modifiche desiderate siano incluse in un commit sul branch principale.
2. Creare esclusivamente il tag `v0.9.0` sul commit da distribuire.
3. Pubblicare il branch e il tag: `git push origin main` e `git push origin v0.9.0`.
4. Il workflow **Build Kerberus** esegue test Python e Go, crea Windows, Linux, wheel, sdist e archivio sorgente, quindi pubblica una sola GitHub Release.
5. Non impostare la release come draft o prerelease: l'updater applicativo legge soltanto l'ultima release stabile.

La release deve contenere almeno:

- `KerberusInstaller.exe`, `Kerberus.exe`, `SHA256SUMS.txt`;
- `Kerberus-linux-x86_64`, `install-linux.sh`, `SHA256SUMS-linux.txt`;
- `Kerberus-0.9.0-src.tar.gz`, wheel, sdist e `SHA256SUMS-source.txt`.

L'aggiornamento automatico usa i nomi stabili dell'installer/portabile e rifiuta il download se il relativo manifest SHA-256 non corrisponde.
