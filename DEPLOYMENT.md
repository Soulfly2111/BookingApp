# Deployment

Diese App kann per GitHub Actions auf einen Linux-Server deployed werden. Die Pipeline liegt in `.github/workflows/deploy.yml`.

## GitHub Secrets

Lege im GitHub-Repository unter `Settings > Secrets and variables > Actions` diese Secrets an:

- `SERVER_HOST`: Hostname oder IP deines Servers
- `SERVER_USER`: SSH-Benutzer
- `SERVER_SSH_KEY`: privater SSH-Key fuer den Deploy-Benutzer
- `DEPLOY_PATH`: Zielordner auf dem Server, z. B. `/var/www/band-booking`

Optional:

- `SERVER_PORT`: SSH-Port, Standard ist `22`
- `SERVICE_NAME`: Systemd-Service, Standard ist `band-booking`

## Server vorbereiten

Auf dem Server sollte Python 3 installiert sein:

```bash
sudo apt update
sudo apt install python3 python3-venv
sudo mkdir -p /var/www/band-booking
sudo chown -R $USER:www-data /var/www/band-booking
```

Der Workflow installiert den Systemd-Service aus `systemd/band-booking.service`, erstellt eine virtuelle Umgebung und startet die App neu.

## App-URL

Der Service lauscht intern auf `127.0.0.1:8000`. Fuer eine oeffentliche Domain empfiehlt sich ein Reverse Proxy mit Nginx oder Apache, der auf diesen lokalen Port weiterleitet.

Die produktive SQLite-Datei liegt standardmaessig unter:

```text
/var/www/band-booking/data/band_concerts.db
```

Sie wird nicht vom Repository ueberschrieben.
