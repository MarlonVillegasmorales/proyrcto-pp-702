# Contexto del Proyecto: Observatorio de la Economía del Cuidado CDMX

## Objetivo General
Desarrollar un sistema integral en Python que incluya un Dashboard interactivo y un modelo de datos. El objetivo es analizar el impacto de las responsabilidades de cuidado en la inserción laboral femenina en la CDMX y proponer un sistema de vinculación (matching) basado en zonas geográficas[cite: 6].

## Eje Metodológico Transformador
El proyecto sigue rigurosamente la secuencia transversal establecida por la UNRC[cite: 6]:
`DATOS -> EVIDENCIA -> DECISIÓN -> PROGRAMA DE INNOVACIÓN SOCIAL`

## Stack Tecnológico Requerido
- Lenguaje: Python 3.10+
- Manipulación de datos: pandas, numpy
- Base de Datos: PostgreSQL / SQLite (Diseño OLTP y OLAP)[cite: 6]
- Datos geoespaciales: geopandas, shapely
- Visualización y Dashboard: streamlit, plotly, matplotlib, folium (para mapas interactivos)
- Algoritmos y Modelado: scikit-learn

## Archivos de Datos (Fuentes)
El repositorio de evidencias integra conjuntos de datos estructurados para el análisis demográfico, económico y geoespacial[cite: 6]:
1. `ENUT_2024_CDMX_resumen_ponderado.csv`: Datos de pobreza de tiempo y horas de cuidado no remunerado.
2. `base_censo_CDMX_observatorio_v1.csv`: Población dependiente (adultos mayores, infantes) por Alcaldía.
3. `Equipamiento_de_asistencia_social.shp` (junto con `.dbf`, `.prj`, `.shx`): Archivo vectorial espacial (Shapefile) proyectado en EPSG:32614. Contiene geometrías de polígonos y una tabla de atributos que detalla la infraestructura de asistencia social instalada (ej. `No_Guard` para guarderías), demografía (`pob_2010`) y está clasificado por `alcaldia` y `cve_col`.
4. `datos_observatorio_cuidado_alcaldias_cdmx.csv`: Base estructurada con 16 filas (alcaldías) y 15 columnas con variables censales, laborales e infraestructura[cite: 6].
5. `indicadores_macro_economia_cuidado.csv`: Tabla de datos macroeconómicos nacionales y capitalinos del Trabajo No Remunerado de los Hogares (TNRH) y brechas de inactividad[cite: 6].

**Nota de Integración de Datos:** El agente deberá cruzar las bases tabulares (CSVs) con el Shapefile (`.shp`) utilizando la variable territorial `alcaldia` mediante `geopandas`. Esto permitirá mapear la oferta de servicios sociales frente a la demanda de cuidado y la pobreza de tiempo territorial.

## Reglas de Negocio e Incidentes Críticos (UCA)

### 1. Leyes para la Protección de Datos (Privacidad Crítica)
- Privacidad por diseño (Privacy by Design): Obligación legal de proteger la privacidad de titulares vulnerables[cite: 6].
- Los datos sensibles de usuarios del piloto que pasen por el modelo de matching deben estar seudonimizados[cite: 6]. Se deben aplicar hashes SHA-256 o UUID a nombres o identificadores directos[cite: 6].
- La arquitectura cuenta con 3 capas: Ingesta (cifrada), Operativa/Matching (seudonimizada) y Analítica (Dashboard público con anonimización irreversible).

### 2. Práctica Profesional I (Piloto Delimitado)
- El programa de vinculación (matching) no debe procesar a todas las personas. El desarrollo está estrictamente delimitado a un piloto realista en el Centro Comunitario 'Manos que Cuidan' (Iztapalapa)[cite: 6], limitando el procesamiento a 15 familias solicitantes y 6 personas cuidadoras en 2 colonias[cite: 6].

### 3. Inteligencia de Negocios
- El dashboard no debe medir únicamente el crecimiento económico[cite: 6]. Debe construir un mapa de KPIs que incluya indicadores de cobertura social, accesibilidad, necesidades no atendidas y brechas territoriales[cite: 6], evidenciando que el cuidado no remunerado afecta la participación económica (PEA) de las mujeres.

### 4. Analítica para los Negocios
- El desarrollo debe centrarse en la creación de "Valor Compartido", conectando la sostenibilidad empresarial con la solución al problema del cuidado y la inserción laboral[cite: 6].

### 5. Herramientas y Técnicas Avanzadas
- El modelo de clasificación/matching (necesito cuidado / puedo cuidar) debe mitigar sesgos territoriales o de género, y documentar claramente sus limitaciones o fallos bajo criterios de transparencia algorítmica[cite: 6].

### 6. Seminario de Titulación I
- Las fallas, baja participación o sesgos del algoritmo no deben ocultarse; deben documentarse con precisión científica[cite: 6].

## Plan de Acción Inmediato (Instrucciones para el Agente)
1. Paso 1: Diseño de la Base de Datos SQL (OLTP para transacciones de matching y OLAP para el Dashboard)[cite: 6].
2. Paso 2: Generación de Pipelines ETL para cruzar los 5 archivos fuente, integrando la dimensión espacial del Shapefile[cite: 6].
3. Paso 3: Codificación del motor de matching con scikit-learn delimitado al piloto en Iztapalapa[cite: 6].
4. Paso 4: Construcción del Dashboard interactivo multicapa en Streamlit, incluyendo mapas coropléticos con GeoPandas[cite: 6].