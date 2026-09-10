"""
Módulo exporter.py para conversión a GeoDataFrames, sanitización de campos (límite DBF 10 caracteres)
y empaquetado a archivos comprimidos .ZIP para Shapefile (SHP) y File Geodatabase (GDB).
"""

import os
import re
import io
import zipfile
import tempfile
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon


def sanitize_column_name(col_name, max_len=10):
    """
    Sanitiza el nombre de una columna para cumplir con las normas de DBF / GIS.
    Elimina caracteres especiales, tildes, espacios y trunca según max_len.
    """
    if col_name.lower() == 'geometry':
        return 'geometry'

    # Reemplazar tildes y caracteres hispanos
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
        'ñ': 'n', 'Ñ': 'N', 'ü': 'u', 'Ü': 'U'
    }
    clean = str(col_name)
    for orig, rep in replacements.items():
        clean = clean.replace(orig, rep)

    # Reemplazar caracteres no alfanuméricos por guion bajo
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', clean)
    # Eliminar guiones bajos consecutivos
    clean = re.sub(r'_+', '_', clean).strip('_')

    if not clean:
        clean = "CAMPO"

    # Truncar si excede el largo máximo
    if max_len and len(clean) > max_len:
        clean = clean[:max_len]

    return clean


def sanitize_dataframe_columns(gdf, max_len=10):
    """
    Sanitiza todas las columnas de un GeoDataFrame manejando posibles duplicaciones
    provocadas por la truncación a 10 caracteres.
    """
    if gdf.empty:
        return gdf

    new_cols = []
    seen = {}

    for col in gdf.columns:
        if col.lower() == 'geometry':
            new_cols.append('geometry')
            continue

        clean = sanitize_column_name(col, max_len=max_len)
        clean_upper = clean.upper()

        if clean_upper not in seen:
            seen[clean_upper] = 1
            new_cols.append(clean)
        else:
            count = seen[clean_upper]
            suffix = f"_{count}"
            seen[clean_upper] += 1

            # Ajustar largo base para que entre el sufijo
            base_len = (max_len - len(suffix)) if max_len else len(clean)
            final_name = f"{clean[:base_len]}{suffix}"
            new_cols.append(final_name)

    gdf_clean = gdf.copy()
    gdf_clean.columns = new_cols
    return gdf_clean


def features_to_geodataframes(features, target_crs="EPSG:4326"):
    """
    Convierte la lista de features extraídas por kml_parser en 3 GeoDataFrames
    categorizados por geometría: Puntos, Líneas y Polígonos.
    """
    points_list = []
    lines_list = []
    polygons_list = []

    for f in features:
        geom = f.get('geometry')
        if geom is None or geom.is_empty:
            continue

        # Crear diccionario completo con propiedades base + atributos extraídos
        row_dict = {
            'Name': f.get('name', ''),
            'Folder': f.get('folder', ''),
            **f.get('attributes', {})
        }
        row_dict['geometry'] = geom

        gtype = geom.geom_type
        if gtype in ('Point', 'MultiPoint'):
            points_list.append(row_dict)
        elif gtype in ('LineString', 'MultiLineString'):
            lines_list.append(row_dict)
        elif gtype in ('Polygon', 'MultiPolygon'):
            polygons_list.append(row_dict)

    gdfs = {}

    for layer_name, data_list in [('Puntos', points_list), ('Lineas', lines_list), ('Poligonos', polygons_list)]:
        if data_list:
            df = pd.DataFrame(data_list)
            gdf = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")
            if target_crs and target_crs != "EPSG:4326":
                try:
                    gdf = gdf.to_crs(target_crs)
                except Exception as e:
                    print(f"Error al reproyectar a {target_crs}: {e}")
            gdfs[layer_name] = gdf
        else:
            gdfs[layer_name] = gpd.GeoDataFrame(columns=['geometry'], crs=target_crs or "EPSG:4326")

    return gdfs


def export_to_shp_zip(gdfs, sanitize_cols=True):
    """
    Exporta los GeoDataFrames a archivos Shapefile (.shp) por tipo de geometría
    y los empaqueta en un archivo .ZIP en memoria.
    Retorna los bytes del ZIP.
    """
    zip_buffer = io.BytesIO()

    with tempfile.TemporaryDirectory() as tmpdir:
        for layer_name, gdf in gdfs.items():
            if gdf.empty or len(gdf) == 0:
                continue

            gdf_export = gdf.copy()
            if sanitize_cols:
                gdf_export = sanitize_dataframe_columns(gdf_export, max_len=10)

            shp_filename = f"{layer_name}.shp"
            shp_path = os.path.join(tmpdir, shp_filename)

            # Exportar a Shapefile con codificación UTF-8
            gdf_export.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")

        # Empaquetar el directorio temporal en el ZIP
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root_dir, _, files in os.walk(tmpdir):
                for file in files:
                    full_path = os.path.join(root_dir, file)
                    arcname = os.path.relpath(full_path, tmpdir)
                    zf.write(full_path, arcname)

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def export_to_gdb_zip(gdfs, gdb_name="Convertido.gdb", sanitize_cols=True):
    """
    Exporta los GeoDataFrames a una File Geodatabase (.gdb)
    usando el driver OpenFileGDB y la comprime en un archivo .ZIP.
    Retorna los bytes del ZIP.
    """
    zip_buffer = io.BytesIO()

    with tempfile.TemporaryDirectory() as tmpdir:
        gdb_path = os.path.join(tmpdir, gdb_name)

        for layer_name, gdf in gdfs.items():
            if gdf.empty or len(gdf) == 0:
                continue

            gdf_export = gdf.copy()
            if sanitize_cols:
                gdf_export = sanitize_dataframe_columns(gdf_export, max_len=64)

            # Guardar capa en el FileGDB
            gdf_export.to_file(gdb_path, driver="OpenFileGDB", layer=layer_name)

        # Empaquetar la carpeta .gdb en el ZIP
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root_dir, _, files in os.walk(gdb_path):
                for file in files:
                    full_path = os.path.join(root_dir, file)
                    arcname = os.path.relpath(full_path, tmpdir)
                    zf.write(full_path, arcname)

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def export_to_geojson_zip(gdfs, sanitize_cols=True):
    """
    Exporta los GeoDataFrames a archivos GeoJSON (.geojson) por tipo de geometría
    y los empaqueta en un archivo .ZIP en memoria.
    Retorna los bytes del ZIP.
    """
    zip_buffer = io.BytesIO()

    with tempfile.TemporaryDirectory() as tmpdir:
        for layer_name, gdf in gdfs.items():
            if gdf.empty or len(gdf) == 0:
                continue

            gdf_export = gdf.copy()
            if sanitize_cols:
                # El GeoJSON no tiene limite estricto de 10 caracteres como SHP, pero sanitizamos caracteres
                gdf_export = sanitize_dataframe_columns(gdf_export, max_len=64)

            geojson_filename = f"{layer_name}.geojson"
            geojson_path = os.path.join(tmpdir, geojson_filename)

            # Convertir fechas o diccionarios a string antes de exportar a GeoJSON
            for col in gdf_export.columns:
                if col != 'geometry' and gdf_export[col].dtype == 'object':
                    gdf_export[col] = gdf_export[col].astype(str)

            gdf_export.to_file(geojson_path, driver="GeoJSON", encoding="utf-8")

        # Empaquetar el directorio temporal en el ZIP
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root_dir, _, files in os.walk(tmpdir):
                for file in files:
                    full_path = os.path.join(root_dir, file)
                    arcname = os.path.relpath(full_path, tmpdir)
                    zf.write(full_path, arcname)

    zip_buffer.seek(0)
    return zip_buffer.getvalue()
