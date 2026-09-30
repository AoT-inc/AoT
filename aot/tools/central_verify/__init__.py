"""동기화한 사본 — 원본은 저장소 aot-auth(gitea `aot/aot-aot-auth`)의 `aot_auth_verify/`(commit 18ee9b2).
고치려면 그 저장소에서 먼저 고치고 이 사본에 그대로 옮긴다 — 여기서만 고치지 않는다.

AoT 중앙 인증(또는 같은 규칙으로 토큰을 내는 인가 서버)의 접근 토큰을 이 AoT(자원 서버)에서 확인한다.
서명(JWKS, ES256 고정) · typ=at+jwt · iss · aud == 이 서버의 MCP 공개 주소(정규형, 정확히) · exp·nbf(오차 60초) ·
폐지 목록(gid, 계정 not_before). JWKS 는 1시간 캐시, 폐지 목록은 1분마다. 인증 서버에 닿지 못하면 마지막 것으로 계속.
"""

from .verifier import CentralTokenVerifier, Claims, IdTokenError, normalize_resource, verify_id_token

__all__ = ["CentralTokenVerifier", "Claims", "IdTokenError", "normalize_resource", "verify_id_token"]
