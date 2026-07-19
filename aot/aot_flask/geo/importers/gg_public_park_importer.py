# coding=utf-8
"""
경기도 도시공원 데이터 임포터

경기데이터드림 CityPark API에서 도시공원 목록을 조회하고,
V-World Data API(도시공원 구역 폴리곤) 또는 기존 parcel_from_address(LP_PA_CBND_BUBUN)로
GeoJSON 폴리곤을 확보한 뒤 GeoShape(site)로 저장한다.

폴리곤 확보 우선순위:
  1. V-World Data API - LT_C_PRKLND (도시공원 구역 경계) — 좌표 기반
  2. V-World Data API - LT_L_PRKLND (공원 경계선) — 좌표 기반
  3. 기존 parcel_from_address — 주소 기반 (LP_PA_CBND_BUBUN)
  4. 포인트만 저장 (폴리곤 없음)
"""

import time
import uuid
import requests

CITYPARK_API_URL = 'https://openapi.gg.go.kr/CityPark'
VWORLD_DATA_API_URL = 'https://api.vworld.kr/req/data'

# V-World 도시공원 데이터셋 (우선순위 순)
PARK_DATASETS = ['LT_C_PRKLND', 'LT_L_PRKLND']


class GgPublicParkImporter:
    """
    경기도 도시공원 GeoShape 일괄 임포터.

    사용 예:
        importer = GgPublicParkImporter(api_key='...', domain='')
        result = importer.import_parks(geo_id='<map_uuid>', sigun_nm='수원시', dry_run=True)
    """

    def __init__(self, api_key: str, domain: str = ''):
        self.vworld_api_key = api_key
        self.vworld_domain = domain

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _domain_param(self) -> str:
        d = self.vworld_domain
        return f'&domain={d}' if d else ''

    @staticmethod
    def _centroid(geom: dict):
        """폴리곤 무게중심(좌표 평균) 또는 포인트 좌표 반환."""
        try:
            gtype = geom.get('type', '')
            if gtype == 'Polygon':
                ring = geom['coordinates'][0]
                lng = sum(p[0] for p in ring) / len(ring)
                lat = sum(p[1] for p in ring) / len(ring)
                return [lng, lat]
            elif gtype == 'MultiPolygon':
                ring = geom['coordinates'][0][0]
                lng = sum(p[0] for p in ring) / len(ring)
                lat = sum(p[1] for p in ring) / len(ring)
                return [lng, lat]
            elif gtype == 'Point':
                return geom['coordinates']
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # CityPark API
    # ------------------------------------------------------------------

    def fetch_parks(self, sigun_nm: str = None, page_size: int = 1000) -> list:
        """
        경기데이터드림 CityPark API에서 도시공원 목록 전건 조회.

        Args:
            sigun_nm: 시군 필터 (예: '수원시'). None이면 경기도 전체.
            page_size: 1회 조회 건수 (최대 1000).

        Returns:
            공원 레코드 리스트 (dict).
        """
        parks = []
        page = 1
        while True:
            params = {'pIndex': page, 'pSize': page_size, 'Type': 'json'}
            if sigun_nm:
                params['SIGUN_NM'] = sigun_nm
            try:
                resp = requests.get(CITYPARK_API_URL, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                # 응답 구조: {"CityPark": [{"head": [{"list_total_count": N}]}, {"row": [...]}]}
                block = data.get('CityPark', [])
                if not block or len(block) < 2:
                    break

                head_list = block[0].get('head', [])
                total = 0
                for h in head_list:
                    if 'list_total_count' in h:
                        total = int(h['list_total_count'])
                        break

                rows = block[1].get('row', [])
                if not rows:
                    break
                parks.extend(rows)

                if len(parks) >= total or len(rows) < page_size:
                    break
                page += 1

            except Exception:
                break

        return parks

    # ------------------------------------------------------------------
    # V-World polygon fetch
    # ------------------------------------------------------------------

    def _fetch_park_polygon_by_coord(self, lat: float, lng: float) -> dict | None:
        """
        V-World Data API에서 좌표 포함 도시공원 폴리곤을 조회한다.
        PARK_DATASETS 순서대로 시도하며 첫 번째 성공 feature를 반환한다.
        """
        for dataset in PARK_DATASETS:
            try:
                url = (
                    f'{VWORLD_DATA_API_URL}'
                    f'?service=data&request=GetFeature&data={dataset}'
                    f'&geomFilter=POINT({lng}%20{lat})&srsName=EPSG:4326'
                    f'&format=json&key={self.vworld_api_key}{self._domain_param()}'
                )
                resp = requests.get(url, timeout=15, verify=False)
                data = resp.json()
                features = (
                    data.get('response', {})
                        .get('result', {})
                        .get('featureCollection', {})
                        .get('features', [])
                )
                if features:
                    feat = features[0]
                    # geometry 유효성 확인
                    geom = feat.get('geometry')
                    if geom and geom.get('type') in ('Polygon', 'MultiPolygon'):
                        return feat
            except Exception:
                continue
        return None

    def _fetch_parcel_by_address(self, address: str) -> dict | None:
        """
        기존 parcel_from_address 로직으로 LP_PA_CBND_BUBUN 필지 폴리곤 조회.
        공원 부지가 일반 지적도 필지와 일치하는 경우에만 유효.
        """
        if not address:
            return None
        try:
            from aot.inputs_gis.gis_vworld import InputModule as VWorldInput
            result = VWorldInput.parcel_from_address(
                address, self.vworld_api_key, self.vworld_domain
            )
            if result.get('ok'):
                return result['feature']
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Feature builder
    # ------------------------------------------------------------------

    def _build_feature(self, geometry: dict, park: dict, polygon_source: str) -> dict:
        """
        GeoJSON Feature 생성.
        properties에 공원 메타데이터와 AoT site 필수 필드를 포함한다.
        """
        node_id = str(uuid.uuid4())
        addr = (park.get('REFINE_ROADNM_ADDR') or park.get('REFINE_LOTNO_ADDR') or '').strip()
        return {
            'type': 'Feature',
            'geometry': geometry,
            'properties': {
                'name': park.get('PARK_NM', ''),
                'category': 'site',
                'aot_type': 'site',
                'node_id': node_id,
                # 데이터 출처
                'source': 'gg_citypark',
                'polygon_source': polygon_source,
                # 공원 속성
                'manage_no': park.get('MANAGE_NO', ''),
                'sigun_nm': park.get('SIGUN_NM', ''),
                'park_div_nm': park.get('PARK_DIV_NM', ''),
                'park_ar_m2': park.get('PARK_AR', ''),
                'addr': addr,
            },
        }

    # ------------------------------------------------------------------
    # Single park resolution
    # ------------------------------------------------------------------

    def resolve_polygon(self, park: dict) -> dict:
        """
        단일 공원 레코드에 대해 폴리곤 또는 포인트 feature를 확보한다.

        Returns:
            {
                'park_nm': str,
                'manage_no': str,
                'sigun_nm': str,
                'polygon_source': str | None,   # 'vworld_park' | 'vworld_parcel' | 'point_only' | None
                'feature': GeoJSON Feature | None,
            }
        """
        park_nm = park.get('PARK_NM', '')
        manage_no = park.get('MANAGE_NO', '')
        sigun_nm = park.get('SIGUN_NM', '')
        lat_str = park.get('REFINE_WGS84_LAT', '')
        lng_str = park.get('REFINE_WGS84_LOGT', '')
        addr = (park.get('REFINE_ROADNM_ADDR') or park.get('REFINE_LOTNO_ADDR') or '').strip()

        base = {
            'park_nm': park_nm,
            'manage_no': manage_no,
            'sigun_nm': sigun_nm,
            'polygon_source': None,
            'feature': None,
        }

        # 1단계: V-World 도시공원 폴리곤 (좌표 기반)
        if lat_str and lng_str:
            try:
                lat, lng = float(lat_str), float(lng_str)
                vw_feat = self._fetch_park_polygon_by_coord(lat, lng)
                if vw_feat:
                    base['feature'] = self._build_feature(vw_feat['geometry'], park, 'vworld_park')
                    base['polygon_source'] = 'vworld_park'
                    return base
            except (ValueError, TypeError):
                pass

        # 2단계: 주소 기반 필지 폴리곤 (LP_PA_CBND_BUBUN)
        if addr:
            parcel_feat = self._fetch_parcel_by_address(addr)
            if parcel_feat:
                geom = parcel_feat.get('geometry', {})
                base['feature'] = self._build_feature(geom, park, 'vworld_parcel')
                base['polygon_source'] = 'vworld_parcel'
                return base

        # 3단계: 폴리곤 없음 → 포인트만 저장
        if lat_str and lng_str:
            try:
                lat, lng = float(lat_str), float(lng_str)
                point_geom = {'type': 'Point', 'coordinates': [lng, lat]}
                base['feature'] = self._build_feature(point_geom, park, 'point_only')
                base['polygon_source'] = 'point_only'
            except (ValueError, TypeError):
                pass

        return base

    # ------------------------------------------------------------------
    # Main import
    # ------------------------------------------------------------------

    def import_parks(
        self,
        geo_id: str,
        sigun_nm: str = None,
        dry_run: bool = False,
        limit: int = None,
        delay_sec: float = 0.3,
    ) -> dict:
        """
        공원 목록을 조회하고 GeoShape(site)로 저장한다.

        Args:
            geo_id: 저장할 GeoMap.unique_id
            sigun_nm: 시군 필터 (None이면 경기도 전체)
            dry_run: True이면 DB 저장 없이 결과만 반환
            limit: 처리할 최대 공원 수 (None이면 전체)
            delay_sec: V-World API 호출 간 지연 (초). Rate limit 방지.

        Returns:
            {
                'total': int,
                'saved': int,
                'polygon_count': int,       # Polygon/MultiPolygon 저장 수
                'point_count': int,         # Point(폴리곤 없음)로 저장된 수
                'skip_count': int,          # 좌표·주소 없어 건너뜀
                'results': [...]            # 각 공원 처리 결과
            }
        """
        parks = self.fetch_parks(sigun_nm=sigun_nm)
        if limit:
            parks = parks[:limit]

        saved = 0
        polygon_count = 0
        point_count = 0
        skip_count = 0
        results = []

        if not dry_run:
            from aot.aot_flask.extensions import db as _db
            from aot.databases.models.geo import GeoShape

        for park in parks:
            time.sleep(delay_sec)

            resolved = self.resolve_polygon(park)
            feature = resolved.get('feature')

            if not feature:
                skip_count += 1
                results.append({
                    'park_nm': resolved['park_nm'],
                    'sigun_nm': resolved['sigun_nm'],
                    'status': 'skip',
                    'reason': '좌표 및 주소 모두 없음',
                })
                continue

            geom_type = (feature.get('geometry') or {}).get('type', '')
            source = resolved['polygon_source']

            if not dry_run:
                shape = GeoShape()
                shape.type = 'site'
                shape.geo_id = geo_id
                shape.layer_group = 'public_park'
                shape.feature = feature
                shape.meta_json = {
                    'import_source': 'gg_citypark',
                    'manage_no': resolved['manage_no'],
                    'park_div': park.get('PARK_DIV_NM', ''),
                    'park_ar_m2': park.get('PARK_AR', ''),
                }
                _db.session.add(shape)
                _db.session.flush()

                # label_aux 자동 생성
                centroid = self._centroid(feature.get('geometry') or {})
                if centroid:
                    node_id = feature['properties'].get('node_id', str(uuid.uuid4()))
                    label_feat = {
                        'type': 'Feature',
                        'geometry': {'type': 'Point', 'coordinates': centroid},
                        'properties': {
                            'aot_type': 'label_aux',
                            'label_name': resolved['park_nm'],
                            'label_area': '',
                            'is_label': True,
                            'parent_type': 'site',
                            'parent_node_id': node_id,
                            'node_id': str(uuid.uuid4()),
                        },
                    }
                    lbl = GeoShape()
                    lbl.type = 'label_aux'
                    lbl.geo_id = geo_id
                    lbl.layer_group = 'public_park'
                    lbl.feature = label_feat
                    _db.session.add(lbl)

                saved += 1

            if geom_type in ('Polygon', 'MultiPolygon'):
                polygon_count += 1
            else:
                point_count += 1

            results.append({
                'park_nm': resolved['park_nm'],
                'sigun_nm': resolved['sigun_nm'],
                'manage_no': resolved['manage_no'],
                'status': 'ok',
                'polygon_source': source,
                'geom_type': geom_type,
            })

        if not dry_run:
            _db.session.commit()

        return {
            'total': len(parks),
            'saved': saved if not dry_run else 0,
            'dry_run': dry_run,
            'polygon_count': polygon_count,
            'point_count': point_count,
            'skip_count': skip_count,
            'results': results,
        }
