import re
from lxml import etree
import xml.etree.ElementTree as ET

xml = b'<?xml version="1.0" encoding="UTF-8"?>\n<kml>\n<gx:test>hello</gx:test>\n</kml>'
kml_content = xml.decode('utf-8')

try:
    parser = etree.XMLParser(recover=True)
    root = etree.fromstring(kml_content.encode('utf-8', errors='ignore'), parser=parser)
    print('lxml success')
except Exception as e:
    print('lxml error:', repr(e))
    kml_content = re.sub(r'(<\/?)[a-zA-Z0-9_-]+:', r'\1', kml_content)
    try:
        root = ET.fromstring(kml_content)
        print('fallback success')
    except Exception as e2:
        print('fallback error:', repr(e2))
