"""
Aplicativo Streamlit para la conversión de archivos KMZ/KML a Shapefile (SHP) y File Geodatabase (GDB).
Extrae geometrías (Puntos, Líneas y Polígonos) y convierte el contenido HTML de los popups <description>
y <ExtendedData> en columnas de la tabla de atributos.
"""

import io
import os
import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from streamlit_folium import st_folium
import zipfile

from kml_parser import load_kmz_or_kml
from exporter import features_to_geodataframes, export_to_shp_zip, export_to_gdb_zip, sanitize_dataframe_columns


st.set_page_config(
    page_title="Conversor KMZ/KML a SHP & GDB",
    page_icon="🗺️",
    layout="wide"
)

# Estilos CSS personalizados
st.markdown("""
    <style>
    .main-header {
        font-size: 2.3rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
    }
    .metric-box {
        background-color: #F3F4F6;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
        border-left: 4px solid #2563EB;
    }
    </style>
""", unsafe_allow_html=True)


def main():
    st.markdown('<div class="main-header">🗺️ Conversor KMZ/KML a SHP & File Geodatabase (GDB)</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Extrae automáticamente Puntos, Líneas y Polígonos y <b>transforma la información de los Popups HTML</b> en atributos tabulares estructurados.</div>', unsafe_allow_html=True)

    # Sidebar - Configuración
    st.sidebar.header("⚙️ Opciones de Conversión")

    export_format = st.sidebar.selectbox(
        "Formato de Salida",
        options=["Shapefile (.zip)", "File Geodatabase (.gdb en .zip)", "Ambos (SHP + GDB)"],
        index=2
    )

    sanitize_cols = st.sidebar.checkbox(
        "Sanitizar nombres de columnas (Sin caracteres especiales)",
        value=True,
        help="Reemplaza tildes, espacios y caracteres especiales por guiones bajos para garantizar compatibilidad GIS."
    )

    max_dbf_len = st.sidebar.slider(
        "Límite de caracteres por columna (DBF)",
        min_value=8,
        max_value=32,
        value=10,
        help="Los archivos Shapefile (.dbf) requieren nombres de columna de máximo 10 caracteres."
    )

    st.sidebar.subheader("🌐 Sistema de Coordenadas (CRS)")
    crs_option = st.sidebar.selectbox(
        "Proyección de Salida",
        options=[
            "EPSG:4326 (WGS 84 - Geográficas)",
            "EPSG:32719 (UTM Zona 19S)",
            "EPSG:32718 (UTM Zona 18S)",
            "EPSG:32717 (UTM Zona 17S)",
            "EPSG:3857 (Web Mercator)",
            "Personalizado"
        ],
        index=0
    )

    if crs_option == "Personalizado":
        target_crs = st.sidebar.text_input("Ingresa el código EPSG (ej: EPSG:32719)", value="EPSG:4326")
    else:
        target_crs = crs_option.split(" ")[0]

    # Carga de archivo KMZ/KML
    uploaded_file = st.file_uploader(
        "Carga tu archivo KMZ o KML aquí",
        type=["kmz", "kml"],
        help="Selecciona un archivo .kmz o .kml que contenga capas y popups con información."
    )

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        filename = uploaded_file.name

        with st.spinner("Procesando archivo KMZ/KML y parseando popups HTML..."):
            try:
                features = load_kmz_or_kml(file_bytes, filename=filename)
            except Exception as e:
                st.error(f"Error al leer el archivo KMZ/KML: {e}")
                return

        if not features:
            st.warning("No se encontraron elementos geográficos (Placemarks) en el archivo subido.")
            return

        # Generar GeoDataFrames
        gdfs = features_to_geodataframes(features, target_crs=target_crs)

        pts_count = len(gdfs['Puntos'])
        lines_count = len(gdfs['Lineas'])
        poly_count = len(gdfs['Poligonos'])
        total_count = pts_count + lines_count + poly_count

        # Recopilar todos los nombres de campos extraídos
        all_attr_keys = set()
        for f in features:
            all_attr_keys.update(f.get('attributes', {}).keys())

        # Métricas principales
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("📍 Total Entidades", total_count)
        col2.metric("📌 Puntos", pts_count)
        col3.metric("📏 Líneas", lines_count)
        col4.metric("🔷 Polígonos", poly_count)
        col5.metric("🏷️ Campos Popup", len(all_attr_keys))

        st.markdown("---")

        # Limpieza de atributos (eliminar basura)
        st.subheader("🧹 Limpieza de Atributos")
        all_cols = set()
        for gdf in gdfs.values():
            all_cols.update([c for c in gdf.columns if c != 'geometry'])
        
        cols_to_drop = st.multiselect(
            "Selecciona los campos que deseas ELIMINAR (se borrarán de todas las capas):",
            options=sorted(list(all_cols)),
            help="Estos campos se omitirán en la previsualización y no se exportarán a los archivos finales (útil para quitar basura)."
        )

        if cols_to_drop:
            for layer_name in gdfs:
                cols_present = [c for c in cols_to_drop if c in gdfs[layer_name].columns]
                if cols_present:
                    gdfs[layer_name] = gdfs[layer_name].drop(columns=cols_present)

        st.markdown("---")

        # Pestañas principales
        tab_tables, tab_map, tab_download = st.tabs([
            "📊 Previsualización de Atributos",
            "🗺️ Mapa Interactivo",
            "📥 Descargar Archivos Convertidos"
        ])

        # Tab 1: Previsualización de Tablas
        with tab_tables:
            st.subheader("Atributos Extraídos por Tipo de Geometría")
            st.info("Los popups HTML en la descripción del KMZ fueron transformados automáticamente en las siguientes columnas de atributos:")

            geom_selected_label = st.radio(
                "Selecciona la capa a visualizar:",
                options=["Puntos", "Líneas", "Polígonos"],
                horizontal=True
            )

            geom_map = {"Puntos": "Puntos", "Líneas": "Lineas", "Polígonos": "Poligonos"}
            geom_selected = geom_map[geom_selected_label]

            current_gdf = gdfs[geom_selected]

            if current_gdf.empty:
                st.warning(f"No se encontraron elementos de tipo {geom_selected_label} en el archivo KMZ.")
            else:
                display_gdf = current_gdf.copy()
                if sanitize_cols:
                    display_gdf = sanitize_dataframe_columns(display_gdf, max_len=max_dbf_len)

                st.markdown(f"**Capa `{geom_selected_label}` ({len(display_gdf)} registros, {len(display_gdf.columns) - 1} atributos)**")
                
                # Mostrar DataFrame excluyendo o formateando la columna geometry
                df_view = pd.DataFrame(display_gdf.drop(columns=['geometry'], errors='ignore'))
                st.dataframe(df_view, width='stretch', height=350)

                # Inspección individual de Popup original
                st.markdown("##### 🔍 Inspeccionar Popup HTML Crudo de una Entidad")
                feature_names = [f"{i+1}: {f.get('name') or 'Sin Nombre'}" for i, f in enumerate(features)]
                selected_idx = st.selectbox("Selecciona un elemento para ver su popup HTML original:", range(len(features)), format_func=lambda i: feature_names[i])
                
                selected_feat = features[selected_idx]
                with st.expander("Ver contenido HTML crudo y atributos parseados"):
                    st.json(selected_feat.get('attributes', {}))
                    st.code(selected_feat.get('description_raw', 'Sin descripción HTML'), language="html")

        # Tab 2: Mapa Interactivo (Folium)
        with tab_map:
            st.subheader("Visualización Geográfica de Capas Extraídas")
            
            # Asegurar que el mapa esté en WGS84 para Folium
            wgs_gdfs = features_to_geodataframes(features, target_crs="EPSG:4326")
            
            # Calcular centro del mapa
            bounds_list = []
            for gdf_layer in wgs_gdfs.values():
                if not gdf_layer.empty:
                    bounds_list.append(gdf_layer.total_bounds)

            if bounds_list:
                minx = min(b[0] for b in bounds_list)
                miny = min(b[1] for b in bounds_list)
                maxx = max(b[2] for b in bounds_list)
                maxy = max(b[3] for b in bounds_list)
                center_lat = (miny + maxy) / 2
                center_lon = (minx + maxx) / 2
                m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles="OpenStreetMap")
            else:
                m = folium.Map(location=[0, 0], zoom_start=2)

            colors = {'Puntos': 'red', 'Lineas': 'blue', 'Poligonos': 'green'}

            for layer_name, gdf_layer in wgs_gdfs.items():
                if gdf_layer.empty:
                    continue

                feature_group = folium.FeatureGroup(name=f"{layer_name} ({len(gdf_layer)})")

                for idx, row in gdf_layer.iterrows():
                    geom = row['geometry']
                    popup_html = f"<b>Nombre:</b> {row.get('Name', '')}<br><b>Capa:</b> {row.get('Folder', '')}<br><hr>"
                    # Agregar primeros atributos
                    for k, v in row.items():
                        if k not in ('geometry', 'Name', 'Folder') and str(v).strip():
                            popup_html += f"<b>{k}:</b> {v}<br>"

                    popup = folium.Popup(popup_html, max_width=300)

                    if geom.geom_type == 'Point':
                        folium.CircleMarker(
                            location=[geom.y, geom.x],
                            radius=6,
                            color=colors[layer_name],
                            fill=True,
                            fill_color=colors[layer_name],
                            fill_opacity=0.7,
                            popup=popup
                        ).add_to(feature_group)
                    elif geom.geom_type in ('LineString', 'MultiLineString'):
                        folium.GeoJson(
                            geom.__geo_interface__,
                            style_function=lambda x, color=colors[layer_name]: {'color': color, 'weight': 3},
                            popup=popup
                        ).add_to(feature_group)
                    elif geom.geom_type in ('Polygon', 'MultiPolygon'):
                        folium.GeoJson(
                            geom.__geo_interface__,
                            style_function=lambda x, color=colors[layer_name]: {'fillColor': color, 'color': color, 'weight': 2, 'fillOpacity': 0.4},
                            popup=popup
                        ).add_to(feature_group)

                feature_group.add_to(m)

            folium.LayerControl().add_to(m)
            st_folium(m, width=1200, height=500)

        # Tab 3: Descarga
        with tab_download:
            st.subheader("📥 Generación y Descarga de Archivos GIS")
            st.markdown("Selecciona y descarga tus archivos procesados listos para abrir en ArcGIS, QGIS o Google Earth Pro:")

            col_dn1, col_dn2 = st.columns(2)

            base_filename = os.path.splitext(filename)[0]

            if export_format in ["Shapefile (.zip)", "Ambos (SHP + GDB)"]:
                with col_dn1:
                    st.markdown("### 📁 ESRI Shapefile (.zip)")
                    st.write("Genera capas Shapefile (`Puntos.shp`, `Lineas.shp`, `Poligonos.shp`) empaquetadas en un único archivo ZIP.")
                    with st.spinner("Empaquetando Shapefile ZIP..."):
                        shp_zip_bytes = export_to_shp_zip(gdfs, sanitize_cols=sanitize_cols)
                    st.download_button(
                        label="⬇️ Descargar Shapefile (.zip)",
                        data=shp_zip_bytes,
                        file_name=f"{base_filename}_SHP.zip",
                        mime="application/zip",
                        key="btn_shp"
                    )

            if export_format in ["File Geodatabase (.gdb en .zip)", "Ambos (SHP + GDB)"]:
                with col_dn2:
                    st.markdown("### 🗄️ File Geodatabase (.gdb ZIP)")
                    st.write("Genera una File Geodatabase (`.gdb`) con Feature Classes para cada tipo de geometría empaquetada en ZIP.")
                    with st.spinner("Generando File Geodatabase..."):
                        gdb_zip_bytes = export_to_gdb_zip(gdfs, gdb_name=f"{base_filename}.gdb", sanitize_cols=sanitize_cols)
                    st.download_button(
                        label="⬇️ Descargar File Geodatabase (.gdb.zip)",
                        data=gdb_zip_bytes,
                        file_name=f"{base_filename}_GDB.zip",
                        mime="application/zip",
                        key="btn_gdb"
                    )

if __name__ == "__main__":
    main()
    # Forzar recarga de modulos
