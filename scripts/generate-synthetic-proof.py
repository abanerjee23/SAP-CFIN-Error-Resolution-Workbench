"""Generate clearly labelled demo evidence, never a representation of a real SAP result.

Run with: uv run --with pillow python scripts/generate-synthetic-proof.py --help
"""
import argparse
import json
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-id', required=True, type=UUID)
    parser.add_argument('--source-document', default='Not supplied')
    parser.add_argument('--output-dir', type=Path, default=Path('.local-runtime/synthetic-proofs'))
    args = parser.parse_args()
    case_id = str(args.case_id)
    reference = 'DEMO-' + case_id[:8].upper()
    image = Image.new('RGB', (1400, 820), '#EDF1F3')
    draw = ImageDraw.Draw(image)
    large = ImageFont.load_default(size=45)
    regular = ImageFont.load_default(size=27)
    small = ImageFont.load_default(size=22)
    draw.rectangle((0, 0, 1400, 155), fill='#283048')
    draw.text((55, 35), 'SYNTHETIC DEMO PROOF', font=large, fill='white')
    draw.text((55, 101), 'Generated example - no SAP system was contacted', font=regular, fill='#FFE4A3')
    draw.rectangle((35, 190, 1365, 685), fill='white')
    lines = [
        ('Case', case_id),
        ('Source document', args.source_document[:100]),
        ('Synthetic target document', reference),
        ('Reprocessing outcome', 'SUCCESSFUL - simulated'),
        ('Data validation', 'PASSED - simulated'),
        ('Evidence purpose', 'Demonstrate upload, review and recorded closure'),
    ]
    for i, (label, value) in enumerate(lines):
        y = 225 + i * 70
        draw.text((60, y), label, font=small, fill='#52616E')
        draw.text((450, y), value, font=regular, fill='#182536')
    draw.text((55, 722), 'This image is test evidence. It does not prove a real posting or reconciliation.', font=small, fill='#A52C3B')
    draw.text((55, 765), 'A person must review the evidence and explicitly record the demo outcome.', font=small, fill='#52616E')
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('cfin_demo_proof', json.dumps({
        'synthetic': True, 'case_id': case_id, 'source_document': args.source_document,
        'posting_reference': reference, 'reprocessing_status': 'successful',
        'validation_status': 'passed', 'system_connection_verified': False,
    }))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f'synthetic-proof-{case_id}.png'
    image.save(path, pnginfo=metadata)
    note = path.with_suffix('.txt')
    note.write_text(
        f'SYNTHETIC DEMO ONLY. Case {case_id}.\n'
        f'Reprocessing: successful (simulated). Data validation: passed (simulated).\n'
        f'Target document: {reference}\n'
        'The attached generated proof was reviewed for this demo. No SAP system was contacted.\n'
    )
    print(path.resolve())
    print(note.resolve())


if __name__ == '__main__':
    main()
