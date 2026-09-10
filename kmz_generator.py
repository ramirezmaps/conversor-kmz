import os
import io
import zipfile
import simplekml
import pandas as pd
from shapely.geometry import Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon

def generate_html_table(row):
    """Genera una tabla HTML atractiva para el popup del KML a partir de un dict (row)"""
    html = '<table style="width:100%; border-collapse: collapse; font-family: sans-serif;">'
    for k, v in row.items():
        if k != 'geometry' and pd.notna(v) and str(v).strip():
            html += f'''
            <tr>
                <td style="padding: 5px; border-bottom: 1px solid #ddd; font-weight: bold; background-color: #f2f2f2;">{k}</td>
                <td style="padding: 5px; border-bottom: 1px solid #ddd;">{v}</td>
            </tr>
            '''
    html += '</table>'
    return html

def _add_geometry_to_kml(container, geom, name, description, style=None):
    if geom is None or geom.is_empty:
        return
    
    geom_type = geom.geom_type
    
    if geom_type == 'Point':
        pnt = container.newpoint(name=name, coords=[(geom.x, geom.y)])
        pnt.description = description
        if style:
            pnt.style = style
            
    elif geom_type == 'LineString':
        ls = container.newlinestring(name=name, coords=list(geom.coords))
        ls.description = description
        if style:
            ls.style = style
            
    elif geom_type == 'Polygon':
        outer = list(geom.exterior.coords)
        inners = [list(i.coords) for i in geom.interiors]
        pol = container.newpolygon(name=name, outerboundaryis=outer, innerboundaryis=inners)
        pol.description = description
        if style:
            pol.style = style
            
    elif geom_type == 'MultiPoint':
        for i, part in enumerate(geom.geoms):
            _add_geometry_to_kml(container, part, f"{name}_{i}", description, style)
            
    elif geom_type == 'MultiLineString':
        for i, part in enumerate(geom.geoms):
            _add_geometry_to_kml(container, part, f"{name}_{i}", description, style)
            
    elif geom_type == 'MultiPolygon':
        for i, part in enumerate(geom.geoms):
            _add_geometry_to_kml(container, part, f"{name}_{i}", description, style)

def export_to_premium_kmz(gdfs_dict, group_by_col=None):
    """
    Toma un diccionario de GeoDataFrames y genera un archivo KMZ en memoria.
    Agrupa los elementos en carpetas si se provee group_by_col.
    Retorna los bytes del KMZ generado.
    """
    kml = simplekml.Kml()
    
    # Crear un estilo base (colores aleatorios o distintos por grupo/capa se podrian agregar)
    # Por ahora, usamos un estilo premium genérico para todo si no hay agrupacion
    # Si hay agrupación o multiples capas, idealmente asignar colores
    
    import branca.colormap as cm
    import matplotlib.colors as mcolors
    palette = list(mcolors.TABLEAU_COLORS.values())
    color_idx = 0
    
    # Para cada capa en el diccionario
    for layer_name, gdf in gdfs_dict.items():
        if gdf.empty:
            continue
            
        # Si queremos reproyectar a wgs84
        if gdf.crs and gdf.crs != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
            
        layer_folder = kml.newfolder(name=layer_name)
        
        # Si se especificó una columna para agrupar que existe en esta capa
        if group_by_col and group_by_col in gdf.columns:
            grouped = gdf.groupby(group_by_col)
            for group_name, group_gdf in grouped:
                group_folder = layer_folder.newfolder(name=str(group_name))
                
                # Crear estilo para este grupo
                hex_color = palette[color_idx % len(palette)]
                kml_color = simplekml.Color.hex(hex_color[1:]) # Quita el # y convierte
                # simplekml Color necesita aabbggrr
                # pero simplekml.Color.hex puede parsear #rrggbb a aabbggrr?
                # Para evitar problemas con simplekml, lo armamos manualmente:
                r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
                kml_color = f"ff{b}{g}{r}" # opacidad ff + bgr
                
                style = simplekml.Style()
                style.linestyle.color = kml_color
                style.linestyle.width = 2
                style.polystyle.color = f"80{b}{g}{r}" # 50% opacity
                # iconstyle color...
                style.iconstyle.color = kml_color
                
                for idx, row in group_gdf.iterrows():
                    geom = row['geometry']
                    desc = generate_html_table(row)
                    name = str(row.get('Name', f"Elemento {idx}"))
                    if name == "nan" or not name.strip():
                        name = f"Elemento {idx}"
                    
                    _add_geometry_to_kml(group_folder, geom, name, desc, style)
                
                color_idx += 1
        else:
            # Sin agrupamiento (o columna no existe)
            style = simplekml.Style()
            hex_color = palette[color_idx % len(palette)]
            r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
            kml_color = f"ff{b}{g}{r}"
            style.linestyle.color = kml_color
            style.linestyle.width = 2
            style.polystyle.color = f"80{b}{g}{r}"
            style.iconstyle.color = kml_color
            
            for idx, row in gdf.iterrows():
                geom = row['geometry']
                desc = generate_html_table(row)
                name = str(row.get('Name', f"Elemento {idx}"))
                if name == "nan" or not name.strip():
                    name = f"Elemento {idx}"
                
                _add_geometry_to_kml(layer_folder, geom, name, desc, style)
            color_idx += 1
            
    # Guardar KML como KMZ (comprimido en memoria)
    kml_str = kml.kml()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('doc.kml', kml_str)
        
    zip_buffer.seek(0)
    return zip_buffer.getvalue()
