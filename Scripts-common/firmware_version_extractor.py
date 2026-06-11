#!/usr/bin/env python3
"""
===============================================================================
 Firmware Version Extractor
===============================================================================
 Extracts firmware version strings/IDs from VCUPlus build artifacts
 (.map + .s19/.hex) without requiring source code.

 Usage:
   python firmware_version_extractor.py <firmware_dir_or_file>

 Examples:
   python firmware_version_extractor.py Output_GM_VCUPLUS_APP_TC397X_debug
   python firmware_version_extractor.py Output_GM_VCUPLUS_BL_TC397X_debug
   python firmware_version_extractor.py Output_GM_VCUPLUS_BM_TC397X_debug

 Output:
   Partition  : APP
   Version ID : 0x01C9C380 (30000000)
   Version    : MAA.RRR.S.BB
===============================================================================
"""

import os
import re
import sys
import glob
import json
import struct
import time


# =============================================================================
# MAP 文件解析器
# =============================================================================

VERSION_SECTION_PATTERNS = {
    'APP': {
        'version_id':     r'\.SW_VERSION_ID\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)',
        'version_string': r'\.SW_VERSION_STRING\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)',
    },
    'BL': {
        'version_id':     r'\.FBL_VERSION_ID\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)',
        'version_string': r'\.FBL_VERSION_STRING\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)',
        'build_timestamp': r'\.FBL_BUILD_TIME_STAMP\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)',
    },
    'BM': {
        'version_string': r'\.BmVersionStringGroup\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)',
        'bm_header':      r'\.BmHeaderSectionGroup\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)',
    },
}


def find_version_addresses_from_map(map_path, partition):
    """Parse .map file to find version section addresses."""
    if partition not in VERSION_SECTION_PATTERNS:
        raise ValueError(f"Unsupported partition: {partition}, choose from {list(VERSION_SECTION_PATTERNS.keys())}")

    patterns = VERSION_SECTION_PATTERNS[partition]
    result = {}

    with open(map_path, 'r', errors='replace') as f:
        content = f.read()

    for field_name, pattern in patterns.items():
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            addr = int(match.group(1), 16)
            size = int(match.group(2), 16)
            result[field_name] = {'address': addr, 'size': size}
            print(f"  [MAP] Found {field_name}: addr=0x{addr:08X}, size={size}B")
        else:
            print(f"  [MAP] {field_name} not found")

    return result


# =============================================================================
# S19 / SREC Parser (Motorola S-record)
# =============================================================================

def parse_s19_records(s19_path):
    """Parse Motorola S-record file into { address: data_bytes } mapping."""
    records = {}
    with open(s19_path, 'r', errors='replace') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line[0] != 'S':
                continue
            record_type = line[1]
            if record_type not in ('1', '2', '3'):
                continue
            try:
                byte_count = int(line[2:4], 16)
                addr_len = {'1': 2, '2': 3, '3': 4}[record_type]
                addr_start = 4
                addr_end = addr_start + addr_len * 2
                addr = int(line[addr_start:addr_end], 16)
                data_str = line[addr_end:-2]
                data = bytes.fromhex(data_str)
                records[addr] = data
            except (ValueError, IndexError) as e:
                print(f"  [WARN] S19 parse error line {line_num}: {e}", file=sys.stderr)
    return records


def find_data_at_address(records, target_addr, size):
    """Find data at a specific address across S19/HEX records."""
    if target_addr in records:
        data = records[target_addr]
        if len(data) >= size:
            return data[:size]

    for addr, data in sorted(records.items()):
        rec_start = addr
        rec_end = addr + len(data)
        if rec_start <= target_addr < rec_end:
            offset = target_addr - rec_start
            available = len(data) - offset
            if available >= size:
                return data[offset:offset + size]
            else:
                result = data[offset:]
                remaining = size - len(result)
                next_addr = rec_end
                if next_addr in records:
                    result += records[next_addr][:remaining]
                return result
    return None


# =============================================================================
# Intel HEX Parser
# =============================================================================

def parse_hex_records(hex_path):
    """Parse Intel HEX file into { address: data_bytes } mapping."""
    records = {}
    extended_linear_addr = 0

    with open(hex_path, 'r', errors='replace') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line[0] != ':':
                continue
            try:
                byte_count = int(line[1:3], 16)
                record_addr = int(line[3:7], 16)
                record_type = int(line[7:9], 16)
                data_str = line[9:9 + byte_count * 2]
                data = bytes.fromhex(data_str) if data_str else b''

                if record_type == 0x00:
                    full_addr = (extended_linear_addr << 16) | record_addr
                    records[full_addr] = data
                elif record_type == 0x04:
                    extended_linear_addr = int(data_str, 16) if data else 0
                elif record_type == 0x01:
                    break
            except (ValueError, IndexError) as e:
                print(f"  [WARN] HEX parse error line {line_num}: {e}", file=sys.stderr)
    return records


# =============================================================================
# Decoders
# =============================================================================

def decode_version_id(data):
    """Decode uint32 version ID (GHS little-endian)."""
    if data is None or len(data) < 4:
        return None, "No data"
    value = int.from_bytes(data[:4], 'little')
    return value, f"0x{value:08X} ({value})"


def decode_version_string(data):
    """Decode null-terminated ASCII version string (max 64 bytes)."""
    if data is None:
        return None, "No data"
    end = data.find(b'\x00')
    if end < 0:
        end = len(data)
    raw = data[:end]
    try:
        text = raw.decode('ascii')
    except UnicodeDecodeError:
        text = raw.decode('ascii', errors='replace')
    if not text.strip('\x00').strip():
        return None, "(empty)"
    return text, text


def decode_timestamp(data):
    """Decode build timestamp string."""
    return decode_version_string(data)


# =============================================================================
# Auto-detection
# =============================================================================

def detect_partition(path):
    """Detect partition type (APP/BL/BM) from path using keywords."""
    upper_path = path.upper().replace('\\', '/')
    # Match _APP_ / _BL_ / _BM_ patterns common in build output directory names
    if '_APP_' in upper_path:
        return 'APP'
    elif '_BL_' in upper_path:
        return 'BL'
    elif '_BM_' in upper_path:
        return 'BM'
    # Fallback: search for APP/BL/BM as whole-word tokens in path components
    parts = upper_path.replace('/', ' ').replace('_', ' ').replace('-', ' ').split()
    for keyword in ('APP', 'BL', 'BM'):
        if keyword in parts:
            return keyword
    return None


def load_project_config():
    """Load ``project_versions.json`` from the same directory as this script."""
    cfg_path = os.path.join(os.path.dirname(__file__), "project_versions.json")
    try:
        with open(cfg_path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def detect_project_from_path(path, config):
    """Detect project name from *path* by matching config keys as tokens.

    Returns the matched key (e.g. ``"VCUPLUS"``) or ``None``.
    """
    tokens = set(
        path.upper().replace("\\", "/").replace("_", " ").replace("-", " ").split()
    )
    for proj in config:
        if proj.upper() in tokens or proj.upper() in path.upper():
            return proj
    return None


def find_map_file(directory):
    """Find .map file in directory (prefer non-byName/byValue)."""
    for file in os.listdir(directory):
        if file.endswith('.map') and not file.endswith('.byName.map') and not file.endswith('.byValue.map'):
            return os.path.join(directory, file)
    maps = glob.glob(os.path.join(directory, '*.map'))
    if maps:
        return maps[0]
    return None


def find_data_file(directory):
    """Find firmware data file, priority: s19(withPP) > s19 > srec > hex > out."""
    for pattern in ['*_withPP.s19', '*_WithPP.s19', '*.s19', '*.srec', '*.hex', '*.out']:
        files = glob.glob(os.path.join(directory, pattern))
        if files:
            return files[0]
    return None


# =============================================================================
# Main
# =============================================================================

FIELD_DISPLAY_NAMES = {
    'version_id': 'Version ID',
    'version_string': 'Version String',
    'build_timestamp': 'Build Timestamp',
    'bm_header': 'BM Header',
}

FIELD_DECODERS = {
    'version_id': decode_version_id,
    'version_string': decode_version_string,
    'build_timestamp': decode_timestamp,
    'bm_header': lambda d: (d.hex(), d.hex()[:32] + '...') if d and len(d) > 16 else (d.hex() if d else None, str(d)),
}


def extract_version(map_path, data_path, partition):
    """Extract version info from .map and .s19/.hex files."""
    print(f"\n{'='*60}")
    print(f"  Firmware Version Extractor")
    print(f"{'='*60}")
    print(f"  Partition: {partition}")
    print(f"  Map File : {map_path}")
    print(f"  Data File: {data_path}")
    print(f"{'='*60}")

    # Step 1: Parse map for version addresses
    print("\n[1/3] Parsing MAP file...")
    version_addrs = find_version_addresses_from_map(map_path, partition)
    if not version_addrs:
        print("  [ERROR] No version info found in MAP file!")
        return None

    # Step 2: Parse firmware data file
    print("\n[2/3] Parsing firmware data file...")
    data_records = {}
    if data_path.endswith('.s19') or data_path.endswith('.srec') or data_path.endswith('.s37'):
        data_records = parse_s19_records(data_path)
        print(f"  Parsed S19/SREC: {len(data_records)} records")
    elif data_path.endswith('.hex'):
        data_records = parse_hex_records(data_path)
        print(f"  Parsed Intel HEX: {len(data_records)} records")
    elif data_path.endswith('.out'):
        print("  [HINT] .out is ELF format - use TRACE32 Data.LOAD.Elf to read symbols")
        return None
    else:
        print(f"  [ERROR] Unsupported format: {data_path}")
        return None

    # Step 3: Extract and decode
    print("\n[3/3] Extracting version data...\n")
    results = {}
    for field_name, info in version_addrs.items():
        addr = info['address']
        size = info['size']
        data = find_data_at_address(data_records, addr, size)

        if field_name in FIELD_DECODERS:
            decoded, display = FIELD_DECODERS[field_name](data)
            results[field_name] = decoded
            label = FIELD_DISPLAY_NAMES.get(field_name, field_name)
            if decoded is not None:
                print(f"  [OK] {label}: {display}")
            else:
                print(f"  [--] {label}: {display}")
        else:
            results[field_name] = data

    print(f"\n{'='*60}")
    return results


# =============================================================================
# Programmatic API (for integration into api_debug.py etc.)
# =============================================================================

def get_version_info(fw_dir, fw_filename, map_path=None, partition_hint=None):
    """Extract version info from build artifacts in *fw_dir*.

    Parameters
    ----------
    fw_dir : str
        Directory containing the .map and .hex/.s19 files.
    fw_filename : str
        Firmware filename (with extension, e.g. ``GM_VCUPLUS_ND_withPP.hex``).
    map_path : str or None
        Explicit path to the .map file.  When ``None`` it is auto-discovered
        via :func:`find_map_file`.
    partition_hint : str or None
        One of ``"APP"``, ``"BL"``, ``"BM"``.  Auto-detected when ``None``.

    Returns
    -------
    dict or None
        A dict with keys ``partition``, ``version_id``, ``version_string``,
        etc. (depending on partition), plus ``map_path``, or ``None`` if
        extraction fails.
    """
    fw_path = os.path.join(fw_dir, fw_filename)
    if not os.path.isfile(fw_path):
        return None

    if map_path is None:
        map_path = find_map_file(fw_dir)
    if not map_path:
        return None

    partition = partition_hint
    if not partition:
        partition = detect_partition(fw_path) or detect_partition(map_path)
    if not partition:
        return None

    version_addrs = find_version_addresses_from_map(map_path, partition)
    if not version_addrs:
        return None

    # Parse the firmware binary file
    if fw_path.endswith(('.s19', '.srec', '.s37')):
        data_records = parse_s19_records(fw_path)
    elif fw_path.endswith('.hex'):
        data_records = parse_hex_records(fw_path)
    elif fw_path.endswith('.out'):
        return None  # .out is ELF — needs TRACE32 to read
    else:
        return None

    results = {'partition': partition, 'map_path': map_path}
    for field_name, info in version_addrs.items():
        addr = info['address']
        size = info['size']
        data = find_data_at_address(data_records, addr, size)
        if field_name in FIELD_DECODERS:
            decoded, _ = FIELD_DECODERS[field_name](data)
            results[field_name] = decoded
        else:
            results[field_name] = data

    return results


def format_version_summary(results):
    """Format version results into a concise one-line summary string."""
    partition = results.get('partition', '???')
    parts = [f"[{partition}]"]

    if 'version_id' in results and results['version_id'] is not None:
        v = results['version_id']
        parts.append(f"ID=0x{v:08X}" if isinstance(v, int) else f"ID={v}")

    if 'version_string' in results and results['version_string']:
        parts.append(f'Version="{results["version_string"]}"')

    if 'build_timestamp' in results and results['build_timestamp']:
        parts.append(f'Build={results["build_timestamp"]}')

    return ' | '.join(parts)


def main():
    if len(sys.argv) < 2:
        print("Usage: python firmware_version_extractor.py <firmware_dir_or_file_path>")
        print("Examples:")
        print("  python firmware_version_extractor.py Build/Output_GM_VCUPLUS_APP_TC397X_debug")
        print("  python firmware_version_extractor.py Output_GM_VCUPLUS_BL_TC397X_debug/SoftwarePackets/Hex_Files/GM_IDC_VCUPLUS_BL.map")
        sys.exit(1)

    input_path = sys.argv[1]

    if os.path.isfile(input_path):
        if input_path.endswith('.map'):
            map_path = input_path
            data_path = find_data_file(os.path.dirname(input_path))
        else:
            data_path = input_path
            map_path = find_map_file(os.path.dirname(input_path))
    elif os.path.isdir(input_path):
        hex_dir = input_path
        if os.path.isdir(os.path.join(input_path, 'SoftwarePackets', 'Hex_Files')):
            hex_dir = os.path.join(input_path, 'SoftwarePackets', 'Hex_Files')
        map_path = find_map_file(hex_dir)
        data_path = find_data_file(hex_dir)
    else:
        print(f"[ERROR] Path not found: {input_path}")
        sys.exit(1)

    if not map_path:
        print("[ERROR] No .map file found!")
        sys.exit(1)
    if not data_path:
        print("[ERROR] No .s19/.hex/.out firmware file found!")
        sys.exit(1)

    partition = detect_partition(input_path) or detect_partition(map_path)
    if not partition:
        base = os.path.basename(map_path).upper()
        if '_BL' in base:
            partition = 'BL'
        elif '_BM' in base:
            partition = 'BM'
        elif 'APP' in base:
            partition = 'APP'
        else:
            print("[ERROR] Cannot auto-detect partition type (APP/BL/BM)")
            sys.exit(1)

    extract_version(map_path, data_path, partition)


if __name__ == '__main__':
    main()
