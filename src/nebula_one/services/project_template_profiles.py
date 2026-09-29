"""Versioned application overlays for immutable, installed modelling templates."""
import json
from pathlib import Path

from ..errors import DomainError
from ..hashing import canonical_json_sha256
from ..runtime_schemas import MethodPackageCreate


def load_profile(roots, installation):
    matches = []
    for root in roots:
        for path in sorted((Path(root) / 'project-templates').glob('*/template.json')):
            profile = json.loads(path.read_text(encoding='utf-8'))
            expected = {'seed_id': installation.seed_id, 'version': installation.seed_version,
                        'bundle_content_sha256': installation.bundle_content_sha256}
            if profile.get('source_seed') != expected:
                continue
            if profile.get('schema_version') != 'nebula_one.project-template.v1':
                raise DomainError(code='PROJECT_TEMPLATE_PROFILE_INVALID', message='Unsupported project template contract.', status_code=409)
            packages = []
            for replacement in profile['method_replacements']:
                package = MethodPackageCreate.model_validate(replacement['package'])
                digest = canonical_json_sha256(package.model_dump(mode='json'))
                if digest != replacement['content_sha256']:
                    raise DomainError(code='PROJECT_TEMPLATE_METHOD_HASH_MISMATCH', message='Project template method content changed.', status_code=409)
                packages.append((replacement['replaces'], package, digest))
            matches.append((profile, canonical_json_sha256(profile), packages))
    if len(matches) > 1:
        raise DomainError(code='PROJECT_TEMPLATE_PROFILE_AMBIGUOUS', message='Multiple project templates claim this exact seed.', status_code=409)
    return matches[0] if matches else None
