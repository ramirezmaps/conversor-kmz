"""
Módulo para el procesamiento de archivos KMZ/KML, extracción de geometrías 
y parseo de información de popups (HTML en <description>) y <ExtendedData>.
"""

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from shapely.geometry import Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon


def unzip_kmz(file_bytes_or_path):
    """
    Descomprime un archivo KMZ (Zip) y extrae el contenido del archivo KML principal.
    Acepta un objeto de bytes o una ruta de archivo.
    """
    if isinstance(file_bytes_or_path, (bytes, bytearray)):
        zip_obj = zipfile.ZipFile(io.BytesIO(file_bytes_or_path))
    else:
        zip_obj = zipfile.ZipFile(file_bytes_or_path)

    kml_files = [f for f in zip_obj.namelist() if f.lower().endswith('.kml')]
    if not kml_files:
        raise ValueError("El archivo KMZ no contiene ningún archivo .kml válido.")

    # Priorizar doc.kml si existe, de lo contrario tomar el primero
    doc_kml = next((f for f in kml_files if f.lower() == 'doc.kml'), kml_files[0])
    return zip_obj.read(doc_kml).decode('utf-8', errors='replace')


def clean_key(key_text):
    """Limpia el nombre de la clave eliminando dos puntos, espacios sobrantes y etiquetas."""
    if not key_text:
        return ""
    key = str(key_text).strip()
    key = re.sub(r'[:=]+$', '', key).strip()
    return key


def parse_popup_html(html_str):
    """
    Parsea el contenido HTML del popup (etiqueta <description>)
    y retorna un diccionario con las claves y valores extraídos.
    """
    attrs = {}
    if not html_str or not str(html_str).strip():
        return attrs

    html_str = str(html_str).strip()
    soup = BeautifulSoup(html_str, 'html.parser')

    # 1. Parsear Tablas HTML
    tables = soup.find_all('table')
    for table in tables:
        rows = table.find_all('tr')
        if not rows:
            continue

        vertical_kv = True
        temp_kv = {}
        for r in rows:
            cols = r.find_all(['td', 'th'])
            col_texts = [c.get_text(strip=True) for c in cols]
            if len(col_texts) == 2:
                k = clean_key(col_texts[0])
                if k:
                    temp_kv[k] = col_texts[1]
            elif len(col_texts) > 0:
                vertical_kv = False

        if vertical_kv and temp_kv:
            attrs.update(temp_kv)
            continue

        if len(rows) >= 2:
            headers = [clean_key(c.get_text(strip=True)) for c in rows[0].find_all(['td', 'th'])]
            for r in rows[1:]:
                vals = [c.get_text(strip=True) for c in r.find_all(['td', 'th'])]
                if len(vals) == len(headers):
                    for h, v in zip(headers, vals):
                        if h:
                            attrs[h] = v

    # 2. Si no hay tablas, parsear etiquetas en negrita <b>, <strong> o <dt>
    if not attrs:
        for tag in soup.find_all(['b', 'strong', 'dt']):
            k = clean_key(tag.get_text(strip=True))
            if k and len(k) < 60:
                next_node = tag.next_sibling
                v = ""
                if next_node:
                    if isinstance(next_node, str):
                        v = next_node.strip()
                    else:
                        v = next_node.get_text(strip=True)
                v = re.sub(r'^[:=]+', '', v).strip()
                if k and v and k not in attrs:
                    attrs[k] = v

    # 3. Parsear líneas con formato Clave: Valor
    if not attrs:
        text = soup.get_text('\n')
        for line in text.splitlines():
            line = line.strip()
            if ':' in line:
                parts = line.split(':', 1)
                k = clean_key(parts[0])
                v = parts[1].strip()
                if k and v and len(k) < 50 and k not in attrs:
                    attrs[k] = v

    return attrs


def extract_extended_data(placemark_elem):
    """
    Extrae atributos presentes en etiquetas <ExtendedData>, <Data> y <SchemaData>/<SimpleData>.
    """
    attrs = {}
    for ext in placemark_elem:
        tag_name = ext.tag.rsplit('}', 1)[-1]
        if tag_name == 'ExtendedData':
            for child in ext:
                child_tag = child.tag.rsplit('}', 1)[-1]
                if child_tag == 'Data':
                    name = child.attrib.get('name', '')
                    val_elem = None
                    for sub in child:
                        if sub.tag.rsplit('}', 1)[-1] == 'value':
                            val_elem = sub
                            break
                    val = val_elem.text.strip() if (val_elem is not None and val_elem.text) else ''
                    if name:
                        attrs[clean_key(name)] = val

                elif child_tag == 'SchemaData':
                    for simple in child:
                        simple_tag = simple.tag.rsplit('}', 1)[-1]
                        if simple_tag == 'SimpleData':
                            name = simple.attrib.get('name', '')
                            val = simple.text.strip() if simple.text else ''
                            if name:
                                attrs[clean_key(name)] = val
    return attrs


def parse_coordinates(coord_text):
    """
    Parsea texto de coordenadas KML ("lon,lat,alt lon,lat,alt ...")
    y retorna una lista de tuplas (lon, lat).
    """
    coords = []
    if not coord_text:
        return coords

    tokens = coord_text.strip().split()
    for token in tokens:
        parts = token.strip().split(',')
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                coords.append((lon, lat))
            except ValueError:
                continue
    return coords


def parse_kml_geometry(elem):
    """
    Parsea elementos geométricos de KML (Point, LineString, Polygon, MultiGeometry)
    y retorna una lista de geometrías Shapely.
    """
    tag = elem.tag.rsplit('}', 1)[-1]
    geoms = []

    if tag == 'Point':
        coord_elem = None
        for sub in elem:
            if sub.tag.rsplit('}', 1)[-1] == 'coordinates':
                coord_elem = sub
                break
        if coord_elem is not None and coord_elem.text:
            pts = parse_coordinates(coord_elem.text)
            if pts:
                geoms.append(Point(pts[0]))

    elif tag == 'LineString':
        coord_elem = None
        for sub in elem:
            if sub.tag.rsplit('}', 1)[-1] == 'coordinates':
                coord_elem = sub
                break
        if coord_elem is not None and coord_elem.text:
            pts = parse_coordinates(coord_elem.text)
            if len(pts) >= 2:
                geoms.append(LineString(pts))

    elif tag == 'Polygon':
        outer_coords = []
        inner_holes = []

        for sub in elem:
            sub_tag = sub.tag.rsplit('}', 1)[-1]
            if sub_tag == 'outerBoundaryIs':
                ring = None
                for child in sub:
                    if child.tag.rsplit('}', 1)[-1] == 'LinearRing':
                        ring = child
                        break
                if ring is not None:
                    c_elem = None
                    for child in ring:
                        if child.tag.rsplit('}', 1)[-1] == 'coordinates':
                            c_elem = child
                            break
                    if c_elem is not None and c_elem.text:
                        outer_coords = parse_coordinates(c_elem.text)
            elif sub_tag == 'innerBoundaryIs':
                ring = None
                for child in sub:
                    if child.tag.rsplit('}', 1)[-1] == 'LinearRing':
                        ring = child
                        break
                if ring is not None:
                    c_elem = None
                    for child in ring:
                        if child.tag.rsplit('}', 1)[-1] == 'coordinates':
                            c_elem = child
                            break
                    if c_elem is not None and c_elem.text:
                        hole_pts = parse_coordinates(c_elem.text)
                        if len(hole_pts) >= 3:
                            inner_holes.append(hole_pts)

        if len(outer_coords) >= 3:
            try:
                geoms.append(Polygon(outer_coords, inner_holes))
            except Exception:
                pass

    elif tag == 'MultiGeometry':
        for child in elem:
            geoms.extend(parse_kml_geometry(child))

    return geoms


def parse_kml_content(kml_content):
    """
    Parsea la totalidad del string XML de un archivo KML.
    Retorna una lista de diccionarios de características ('features').
    """
    try:
        from lxml import etree
        # Usar lxml con recover=True para ignorar errores de XML malformado como "unbound prefix" (ej: gx:)
        parser = etree.XMLParser(recover=True)
        root = etree.fromstring(kml_content.encode('utf-8', errors='ignore'), parser=parser)
    except ImportError:
        # Fallback agresivo si lxml no está disponible
        kml_content = re.sub(r'(<\/?)[a-zA-Z0-9_-]+:', r'\1', kml_content)
        root = ET.fromstring(kml_content)
        
    features = []

    def recursive_parse(elem, current_folder_path=""):
        tag = elem.tag.rsplit('}', 1)[-1]

        folder_name = current_folder_path
        if tag in ('Folder', 'Document'):
            name_elem = None
            for child in elem:
                if child.tag.rsplit('}', 1)[-1] == 'name':
                    name_elem = child
                    break
            if name_elem is not None and name_elem.text:
                new_folder = name_elem.text.strip()
                folder_name = f"{current_folder_path}/{new_folder}" if current_folder_path else new_folder

        if tag == 'Placemark':
            # 1. Nombre
            name = ""
            name_elem = None
            for child in elem:
                if child.tag.rsplit('}', 1)[-1] == 'name':
                    name_elem = child
                    break
            if name_elem is not None and name_elem.text:
                name = name_elem.text.strip()

            # 2. Descripción (HTML Popup)
            desc_raw = ""
            desc_elem = None
            for child in elem:
                if child.tag.rsplit('}', 1)[-1] == 'description':
                    desc_elem = child
                    break
            if desc_elem is not None and desc_elem.text:
                desc_raw = desc_elem.text

            # Parsear HTML popup
            attributes = parse_popup_html(desc_raw)

            # 3. Extraer ExtendedData
            ext_attrs = extract_extended_data(elem)
            attributes.update(ext_attrs)

            # 4. Extraer Geometrías
            geoms = []
            for child in elem:
                child_tag = child.tag.rsplit('}', 1)[-1]
                if child_tag in ('Point', 'LineString', 'Polygon', 'MultiGeometry'):
                    geoms.extend(parse_kml_geometry(child))

            # Crear una feature por cada geometría encontrada
            for g in geoms:
                features.append({
                    'name': name,
                    'folder': folder_name,
                    'description_raw': desc_raw,
                    'attributes': dict(attributes),
                    'geometry': g
                })
            return

        # Recorrer todos los hijos
        for child in elem:
            recursive_parse(child, folder_name)

    recursive_parse(root)
    return features


def load_kmz_or_kml(file_bytes_or_path, filename=""):
    """
    Función de entrada principal. Recibe bytes o ruta de un archivo KMZ o KML
    y retorna la lista de características procesadas.
    """
    if isinstance(file_bytes_or_path, (bytes, bytearray)):
        if filename.lower().endswith('.kmz') or (len(file_bytes_or_path) > 4 and file_bytes_or_path[:4] == b'PK\x03\x04'):
            try:
                kml_text = unzip_kmz(file_bytes_or_path)
            except Exception:
                kml_text = file_bytes_or_path.decode('utf-8', errors='replace')
        else:
            kml_text = file_bytes_or_path.decode('utf-8', errors='replace')
    else:
        if filename.lower().endswith('.kmz') or file_bytes_or_path.lower().endswith('.kmz'):
            kml_text = unzip_kmz(file_bytes_or_path)
        else:
            with open(file_bytes_or_path, 'r', encoding='utf-8', errors='replace') as f:
                kml_text = f.read()

    return parse_kml_content(kml_text)
