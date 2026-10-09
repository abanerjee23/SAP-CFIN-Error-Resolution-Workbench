"""Read only the optional case binding in our explicitly synthetic PNG fixtures."""
import json
import struct
import zlib
from uuid import UUID

from fastapi import HTTPException


def validate_demo_proof(content: bytes, case_id: UUID) -> None:
    if not content.startswith(b'\x89PNG\r\n\x1a\n'):
        return
    offset = 8
    while offset + 12 <= len(content):
        size = struct.unpack('>I', content[offset:offset + 4])[0]
        kind = content[offset + 4:offset + 8]
        end = offset + 12 + size
        if end > len(content):
            raise HTTPException(422, 'The PNG proof is truncated')
        data = content[offset + 8:end - 4]
        crc = struct.unpack('>I', content[end - 4:end])[0]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != crc:
            raise HTTPException(422, 'The PNG proof failed integrity verification')
        if kind == b'tEXt' and data.startswith(b'cfin_demo_proof\0'):
            try:
                value = json.loads(data.split(b'\0', 1)[1])
            except (ValueError, UnicodeDecodeError) as exc:
                raise HTTPException(422, 'Invalid synthetic proof metadata') from exc
            if (not isinstance(value, dict) or value.get('synthetic') is not True
                    or value.get('case_id') != str(case_id)
                    or value.get('system_connection_verified') is not False):
                raise HTTPException(422, 'The synthetic proof belongs to a different case')
        offset = end
        if kind == b'IEND':
            return
    raise HTTPException(422, 'The PNG proof is incomplete')
