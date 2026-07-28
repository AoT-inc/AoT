#!/usr/bin/env python3
# coding=utf-8
"""SBOM(CycloneDX 1.5 JSON) 생성 — 공급망 보안 산출물.

공공조달·보안진단에서 "이 제품이 무엇으로 만들어졌는가"를 요구한다. 설치된
파이썬 배포판 메타데이터(importlib.metadata)를 읽어 CycloneDX 1.5 형식으로
내보낸다.

**의존성을 추가하지 않았다.** cyclonedx-python-lib 를 쓰면 requirements.txt 가
늘고 Docker 이미지 재빌드가 필요한데(이 저장소 이미지엔 virtualenv 도 setuid
래퍼도 없어 dependencies_module 자동설치가 동작하지 않는다), CycloneDX 는
JSON 스키마라 표준 라이브러리로 충분하다.

사용:
    python3 aot/scripts/generate_sbom.py                  # stdout
    python3 aot/scripts/generate_sbom.py -o sbom.json     # 파일로
    python3 aot/scripts/generate_sbom.py --osv            # OSV 취약점 조회 병행

--osv 는 https://api.osv.dev 에 패키지명+버전만 보내 알려진 취약점을 조회한다
(인증 불필요, 코드나 사내 정보는 전송하지 않는다). 네트워크가 없으면 건너뛴다.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

try:
    from importlib import metadata as importlib_metadata
except ImportError:  # Python < 3.8
    import importlib_metadata

OSV_BATCH_URL = 'https://api.osv.dev/v1/querybatch'
OSV_VULN_URL = 'https://api.osv.dev/v1/vulns/'


def _purl(name, version):
    """Package URL (CycloneDX 가 컴포넌트 식별에 쓰는 표준 문자열)."""
    return 'pkg:pypi/{}@{}'.format(name.lower().replace('_', '-'), version)


def collect_components():
    """설치된 배포판 → CycloneDX 컴포넌트 목록."""
    seen = {}
    for dist in importlib_metadata.distributions():
        try:
            name = dist.metadata['Name']
            version = dist.version
        except Exception:
            continue
        if not name or not version:
            continue
        key = name.lower()
        if key in seen:
            continue

        licenses = []
        lic = dist.metadata.get('License')
        if lic and lic.lower() not in ('unknown', 'none'):
            licenses.append({'license': {'name': lic[:120]}})
        else:
            # License 필드가 비어도 분류자(Classifier)에 들어 있는 경우가 많다
            for classifier in dist.metadata.get_all('Classifier') or []:
                if classifier.startswith('License ::'):
                    licenses.append(
                        {'license': {'name': classifier.split('::')[-1].strip()}})
                    break

        component = {
            'type': 'library',
            'name': name,
            'version': version,
            'purl': _purl(name, version),
        }
        if licenses:
            component['licenses'] = licenses
        author = dist.metadata.get('Author')
        if author:
            component['author'] = author[:120]

        seen[key] = component

    return [seen[k] for k in sorted(seen)]


def build_sbom(components, app_version):
    return {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.5',
        'version': 1,
        'metadata': {
            'component': {
                'type': 'application',
                'name': 'AoT',
                'version': app_version,
            },
            'tools': [{'name': 'aot/scripts/generate_sbom.py'}],
        },
        'components': components,
    }


def query_osv(components):
    """OSV 에 일괄 조회. (purl -> [취약점 id]) 반환. 실패 시 None."""
    queries = [{'package': {'name': c['name'].lower().replace('_', '-'),
                            'ecosystem': 'PyPI'},
                'version': c['version']}
               for c in components]

    findings = {}
    # OSV querybatch 는 요청당 개수 제한이 있어 나눠 보낸다
    for start in range(0, len(queries), 100):
        chunk = queries[start:start + 100]
        payload = json.dumps({'queries': chunk}).encode('utf-8')
        req = urllib.request.Request(
            OSV_BATCH_URL, data=payload,
            headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except (urllib.error.URLError, OSError, ValueError) as err:
            print('OSV 조회 실패(네트워크 문제일 수 있음): %s' % err,
                  file=sys.stderr)
            return None

        for offset, result in enumerate(data.get('results', [])):
            vulns = result.get('vulns') or []
            if vulns:
                comp = components[start + offset]
                findings[comp['purl']] = [v['id'] for v in vulns]

    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-o', '--output', help='출력 파일(기본: stdout)')
    parser.add_argument('--osv', action='store_true',
                        help='OSV 로 알려진 취약점 조회')
    parser.add_argument('--fail-on-vuln', action='store_true',
                        help='취약점이 하나라도 있으면 종료코드 1 (CI 용)')
    args = parser.parse_args()

    try:
        from aot.config import AOT_VERSION
    except Exception:
        AOT_VERSION = 'unknown'

    components = collect_components()
    sbom = build_sbom(components, AOT_VERSION)

    text = json.dumps(sbom, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as fh:
            fh.write(text + '\n')
        print('SBOM 저장: %s (컴포넌트 %d개)' % (args.output, len(components)))
    else:
        print(text)

    if not args.osv:
        return 0

    findings = query_osv(components)
    if findings is None:
        return 0   # 조회 자체가 안 된 것은 취약점 발견과 구분한다

    print('\n=== OSV 취약점 조회 결과 ===', file=sys.stderr)
    if not findings:
        print('알려진 취약점 없음 (컴포넌트 %d개 조회)' % len(components),
              file=sys.stderr)
        return 0

    for purl in sorted(findings):
        print('  %-45s %s' % (purl, ', '.join(findings[purl])), file=sys.stderr)
    print('\n취약 컴포넌트 %d개' % len(findings), file=sys.stderr)

    return 1 if args.fail_on_vuln else 0


if __name__ == '__main__':
    sys.exit(main())
