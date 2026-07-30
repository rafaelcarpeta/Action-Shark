import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CheatEntry:
    id: int
    description: str
    variable_type: str
    address: str
    has_lua: bool = False
    has_aa: bool = False
    has_value: bool = False
    default_value: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    is_group: bool = False
    group_name: str = ""
    children: list['CheatEntry'] = field(default_factory=list)


def _guess_default(variable_type: str) -> tuple:
    vtype = variable_type.lower()
    if 'byte' in vtype:
        return (999, 0, 255)
    elif 'word' in vtype and 'qword' not in vtype:
        return (9999, 0, 65535)
    elif 'qword' in vtype:
        return (999999, 0, 999999999)
    elif 'float' in vtype or 'double' in vtype:
        return (1.0, 0.0, 999999.0)
    elif vtype in ('4 bytes', 'integer', 'int', 'dword'):
        return (9999, 0, 99999999)
    elif 'string' in vtype:
        return (None, None, None)
    return (9999, 0, 99999999)


def _parse_entry(xml_entry) -> CheatEntry:
    id_el = xml_entry.find('ID')
    desc_el = xml_entry.find('Description')
    vt_el = xml_entry.find('VariableType')
    addr_el = xml_entry.find('Address')
    lua_el = xml_entry.find('LuaScript')
    aa_el = xml_entry.find('AssemblerScript')
    gh_el = xml_entry.find('GroupHeader')

    entry_id = int(id_el.text) if id_el is not None and id_el.text else 0
    description = desc_el.text.strip('"') if desc_el is not None and desc_el.text else ""
    variable_type = vt_el.text if vt_el is not None and vt_el.text else ""
    address = addr_el.text if addr_el is not None and addr_el.text else ""
    has_lua = lua_el is not None and lua_el.text and lua_el.text.strip()
    has_aa = aa_el is not None and aa_el.text and aa_el.text.strip()

    is_group = gh_el is not None and gh_el.text == '1'

    has_value = (not is_group and variable_type
                 and variable_type != 'Auto Assembler Script'
                 and variable_type != 'String'
                 and not has_lua and not has_aa)

    default_value = None
    min_value = None
    max_value = None
    if has_value:
        dv, mn, mx = _guess_default(variable_type)
        default_value = dv
        min_value = mn
        max_value = mx

    return CheatEntry(
        id=entry_id,
        description=description,
        variable_type=variable_type,
        address=address,
        has_lua=has_lua,
        has_aa=has_aa,
        has_value=has_value,
        default_value=default_value,
        min_value=min_value,
        max_value=max_value,
        is_group=is_group,
    )


def parse_ct(path: str) -> list[CheatEntry]:
    tree = ET.parse(path)
    root = tree.getroot()
    entries = root.findall('.//CheatEntry')

    result = []
    for xml_entry in entries:
        entry = _parse_entry(xml_entry)
        if entry.is_group:
            result.append(entry)
        elif entry.description or entry.variable_type:
            result.append(entry)

    return result


def parse_ct_grouped(path: str) -> list[CheatEntry]:
    tree = ET.parse(path)
    root = tree.getroot()

    def _parse_children(parent_xml) -> list[CheatEntry]:
        children = []
        for xml_entry in parent_xml.findall('CheatEntry'):
            entry = _parse_entry(xml_entry)
            sub = xml_entry.find('CheatEntries')
            if sub is not None:
                entry.children = _parse_children(sub)
                entry.is_group = True
                if not entry.description:
                    entry.description = "(group)"
            children.append(entry)
        return children

    from collections import OrderedDict
    group_map = OrderedDict()
    for xml_entry in root.findall('.//CheatEntry'):
        parent = None
        p = xml_entry
        while True:
            par_entries = root.findall('.//CheatEntries/CheatEntry')
            break

    entries = root.findall('CheatEntries/CheatEntry') if root.find('CheatEntries') is not None else []
    if not entries:
        entries = root.findall('.//CheatEntry')
        seen = set()
        unique = []
        for e in entries:
            id_str = (e.find('ID').text if e.find('ID') is not None else '') + (e.find('Description').text if e.find('Description') is not None else '')
            if id_str not in seen:
                seen.add(id_str)
                unique.append(e)
        entries = unique

    result = []
    for xml_entry in entries:
        entry = _parse_entry(xml_entry)
        sub = xml_entry.find('CheatEntries')
        if sub is not None:
            entry.children = _parse_children(sub)
            if not entry.is_group and entry.children:
                entry.is_group = True
        result.append(entry)

    return result


def scan_ct_folder(folder_path: str) -> list[str]:
    import os
    files = []
    for f in sorted(os.listdir(folder_path)):
        if f.lower().endswith('.ct'):
            files.append(os.path.join(folder_path, f))
    return files


if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else '/home/carpeta/Backup/Arquivos/trainers/CE Tables/sekiro.CT'
    entries = parse_ct(path)
    print(f'Total entries: {len(entries)}')
    groups = [e for e in entries if e.is_group]
    cheats = [e for e in entries if not e.is_group]
    print(f'Groups: {len(groups)}, Cheats: {len(cheats)}')
    for e in cheats[:10]:
        print(f'  [{e.id}] {e.description[:50]} | {e.variable_type} | has_value={e.has_value} val={e.default_value}')
