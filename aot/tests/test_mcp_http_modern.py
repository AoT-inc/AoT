"""MCP http 의 2026-07-28(현대 방식) 응답과 요청 한 줄 기록 (2026-11-08).

claude.ai 음성 모드에서 이 서버만 도구 목록에서 빠졌다. 같은 계정의 SDK 2.x 서버(server/discover
에 답함)는 보였고, 이 서버는 discover 에 200 + "없는 메서드" 로 답하고 있었다. 현대 요청에는
규격대로 답하고, 구 방식(initialize) 연결은 하나도 바뀌지 않는지 본다.
"""
from aot.tests.test_mcp_resources import _ResBase

_V = "2026-07-28"


def _meta(version=_V):
    return {"_meta": {"io.modelcontextprotocol/protocolVersion": version,
                      "io.modelcontextprotocol/clientInfo": {"name": "voice-test", "version": "1"},
                      "io.modelcontextprotocol/clientCapabilities": {}}}


class ModernHttpTest(_ResBase):

    def _post(self, method, params=None, version=_V, msg_id=1):
        body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            body["params"] = params
        headers = {"MCP-Protocol-Version": version, "Mcp-Method": method} if version else {}
        return self._client().post("/mcp", json=body, headers=headers)

    def test_discover_answers_with_the_modern_version_identity_and_instructions(self):
        r = self._post("server/discover", _meta())
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        res = r.get_json()["result"]
        self.assertEqual(res["supportedVersions"], [_V])
        self.assertEqual(res["resultType"], "complete")
        self.assertEqual((res["ttlMs"], res["cacheScope"]), (0, "private"))
        self.assertIn("tools", res["capabilities"])
        self.assertEqual(res["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "aot-mcp-server")
        self.assertTrue(res["instructions"])
        self.assertNotIn("Mcp-Session-Id", r.headers)        # 현대 방식은 세션을 만들지 않는다

    def test_discover_without_meta_but_with_the_modern_header_is_still_modern(self):
        r = self._post("server/discover", {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["result"]["supportedVersions"], [_V])

    def test_unknown_modern_version_is_400_with_the_supported_list(self):
        r = self._post("server/discover", _meta("2099-01-01"), version="2099-01-01")
        self.assertEqual(r.status_code, 400)
        err = r.get_json()["error"]
        self.assertEqual(err["code"], -32022)
        self.assertEqual(err["data"], {"supported": [_V], "requested": "2099-01-01"})

    def test_modern_tools_list_and_call_carry_the_required_fields(self):
        r = self._post("tools/list", _meta())
        self.assertEqual(r.status_code, 200)
        res = r.get_json()["result"]
        self.assertTrue(res["tools"])
        self.assertEqual((res["resultType"], res["ttlMs"], res["cacheScope"]),
                         ("complete", 0, "private"))
        r = self._post("tools/call", dict(_meta(), name="screen_action",
                                          arguments={"action": "post", "message": "hi"}))
        self.assertEqual(r.status_code, 200)
        res = r.get_json()["result"]
        self.assertEqual(res["resultType"], "complete")
        self.assertNotIn("ttlMs", res)                        # 호출 결과는 캐시 대상이 아니다
        self.assertTrue(res["content"])

    def test_modern_unknown_method_is_404(self):
        r = self._post("nope/nothing", _meta())
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"]["code"], -32601)

    def test_legacy_requests_are_unchanged(self):
        r = self._post("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "legacy", "version": "1"}},
                       version=None)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Mcp-Session-Id", r.headers)
        self.assertNotIn("resultType", r.get_json()["result"])
        r = self._post("tools/list", {}, version="2025-06-18")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("resultType", r.get_json()["result"])
        # 구 클라이언트가 discover 를 보내면 지금처럼 200 + 없는 메서드(구 방식 오류 응답).
        r = self._post("server/discover", {}, version="2025-06-18")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["error"]["code"], -32601)

    def test_every_post_leaves_one_line_without_tokens_or_arguments(self):
        with self.assertLogs("aot_mcp_server", level="INFO") as cm:
            self._post("server/discover", _meta())
            self._post("tools/call", dict(_meta(), name="screen_action",
                                          arguments={"action": "post", "message": "secret-arg"}))
        lines = [l for l in cm.output if "[AoTMCP] http " in l]
        self.assertTrue(any("server/discover proto=2026-07-28 modern=2026-07-28 "
                            "client=voice-test/1 -> 200" in l for l in lines), lines)
        self.assertTrue(any("tools/call screen_action" in l for l in lines), lines)
        self.assertFalse(any("secret-arg" in l for l in lines))

    def test_rejected_auth_is_logged_with_its_method(self):
        self.auth = (False, None, None, {"error": "invalid_token", "message": "x"})
        with self.assertLogs("aot_mcp_server", level="INFO") as cm:
            r = self._post("server/discover", _meta())
        self.assertEqual(r.status_code, 401)
        self.assertTrue(any("server/discover" in l and "-> 401 err=invalid_token" in l
                            for l in cm.output), cm.output)
