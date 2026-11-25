FROM python:3.12-slim-trixie

RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-21-jre-headless \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "anvil-app-server==1.18.0" "psycopg[binary]==3.3.9" "openpyxl==3.1.5"

WORKDIR /srv
COPY cyclops_app /srv/cyclops_app
COPY craftify_library /srv/craftify_library
COPY tabulator /srv/tabulator
COPY anvil_extras /srv/anvil_extras
COPY routing /srv/routing
COPY entrypoint.sh /srv/entrypoint.sh
RUN chmod +x /srv/entrypoint.sh

EXPOSE 3040
ENTRYPOINT ["/srv/entrypoint.sh"]
