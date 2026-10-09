import json
import struct
import zlib
from uuid import UUID

import pytest
from fastapi import HTTPException

from cfin.demo_proof import validate_demo_proof

CASE = UUID('33333333-3333-4333-8333-333333333333')


def chunk(kind, content):
    return (struct.pack('>I', len(content)) + kind + content
            + struct.pack('>I', zlib.crc32(kind + content) & 0xFFFFFFFF))


def proof(case_id):
    body = b'cfin_demo_proof\0' + json.dumps({
        'synthetic': True, 'case_id': str(case_id), 'system_connection_verified': False,
    }).encode()
    return b'\x89PNG\r\n\x1a\n' + chunk(b'tEXt', body) + chunk(b'IEND', b'')


def test_generated_proof_stays_bound_to_its_case():
    validate_demo_proof(proof(CASE), CASE)
    with pytest.raises(HTTPException, match='different case'):
        validate_demo_proof(proof(UUID('44444444-4444-4444-8444-444444444444')), CASE)


def test_changed_metadata_and_truncated_files_are_rejected():
    altered = bytearray(proof(CASE))
    altered[40] ^= 1
    with pytest.raises(HTTPException, match='integrity'):
        validate_demo_proof(bytes(altered), CASE)
    with pytest.raises(HTTPException, match='truncated|incomplete'):
        validate_demo_proof(proof(CASE)[:-2], CASE)
