#!/bin/bash
# Docker lo corre al crear la base, después de 01_esquema.sql y 02_datos_demo.sql:
# aplica todos los archivos de db/migraciones/ en orden alfabético.
# Las migraciones se pueden correr más de una vez, así que no importa que algunas
# ya estén incluidas en 01_esquema.sql.
# En pgAdmin este archivo no se usa: allí cada migración se abre y se ejecuta a mano.
set -e

for archivo in /migraciones/*.sql; do
    [ -e "$archivo" ] || continue
    echo "Migración: $archivo"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$archivo"
done
