# =============================================================================
#  Compiscript — imagen del compilador y del IDE
#
#  Contiene Java (para ejecutar ANTLR), Python y todas las dependencias, de
#  modo que el proyecto se pueda compilar y ejecutar sin instalar nada en la
#  maquina anfitriona.
#
#  Construir:  docker build -t compiscript .
#  Tests:      docker run --rm compiscript
#  IDE:        docker run --rm -p 5000:5000 compiscript ide
#  Analizar:   docker run --rm -v "$(pwd):/trabajo" compiscript cli /trabajo/programa.cps
# =============================================================================
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Compiscript"
LABEL org.opencontainers.image.description="Analizador sintactico y semantico de Compiscript (ANTLR4)"

# Java es necesario unicamente para regenerar el lexer/parser desde la gramatica.
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Las dependencias primero, para aprovechar la cache de capas de Docker.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Codigo del proyecto
COPY grammar/       ./grammar/
COPY src/           ./src/
COPY ide/           ./ide/
COPY tests/         ./tests/
COPY tools/         ./tools/
COPY docs/          ./docs/
COPY pyproject.toml README.md ./
COPY compiscript/antlr-4.13.1-complete.jar ./compiscript/
# El programa de ejemplo del curso: la bateria lo usa como prueba de regresion.
COPY compiscript/program/program.cps ./compiscript/program/

# Se regenera el parser dentro de la imagen: asi se garantiza que el codigo
# generado corresponde exactamente a la gramatica de este repositorio.
RUN python tools/generate_parser.py

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV FLASK_RUN_HOST=0.0.0.0

EXPOSE 5000

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["test"]
