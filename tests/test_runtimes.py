import unittest

from tests.helpers import ROOT  # noqa: F401
from studio.runtimes import classify_error, parse_json_loose, summarize_codex_events


class CodexEvents(unittest.TestCase):
    def test_response_model_metadata_reads_nested_provider_response(self):
        from studio.runtimes import response_model_metadata
        events = [{"type": "session_meta", "model": "configured-model"},
                  {"type": "response.created", "response": {"model": "initial-response"}},
                  {"type": "response.completed", "response": {"model": "served-response"}}]
        self.assertEqual(response_model_metadata(events), ("served-response", "response.completed.response.model"))

    def test_response_model_metadata_reads_explicit_flat_response(self):
        from studio.runtimes import response_model_metadata
        self.assertEqual(response_model_metadata([{"type": "response.completed", "model": "served"}]),
                         ("served", "response.completed.model"))

    def test_local_config_and_assistant_identity_claim_are_not_provider_proof(self):
        from studio.runtimes import response_model_metadata
        events = [{"type": "session.created", "model": "configured"}, {"type": "session_meta", "model": "configured"},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": 'I am served. {"model":"served"}'}},
                  {"type": "turn.completed", "usage": {"model": "requested"}}]
        self.assertEqual(response_model_metadata(events), (None, None))

    def test_malformed_model_identity_is_not_recorded(self):
        from studio.runtimes import response_model_metadata
        for value in [None, 12, {}, "", "x\nforged", "x" * 201]:
            with self.subTest(value=value):
                self.assertEqual(response_model_metadata([{"type": "response.completed", "response": {"model": value}}]),
                                 (None, None))

    def test_summarize(self):
        events = [
            {"type": "thread.started", "thread_id": "x"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "i0", "type": "agent_message", "text": "시작합니다"}},
            {"type": "item.completed", "item": {"id": "i1", "type": "command_execution", "command": '"C:\\\\pwsh.exe" -Command "Get-ChildItem"', "exit_code": 0}},
            {"type": "item.completed", "item": {"id": "i2", "type": "file_change", "changes": [{"path": "S:/x/src/core/run_state.gd", "kind": "update"}]}},
            {"type": "item.completed", "item": {"id": "i3", "type": "error", "message": "경고"}},
            {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 5}},
        ]
        steps, messages, errors, warnings, usage = summarize_codex_events(events)
        self.assertEqual(messages, ["시작합니다"])
        self.assertEqual([s["kind"] for s in steps], ["message", "command", "files"])
        self.assertEqual(steps[1]["text"], "Get-ChildItem")
        self.assertEqual(steps[2]["text"], "run_state.gd")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, ["경고"])
        self.assertEqual(usage["input_tokens"], 100)

    def test_failed_turn(self):
        events = [{"type": "turn.failed", "error": {"message": "The 'gpt-x' model is not supported when using Codex with a ChatGPT account."}}]
        _, _, errors, _, _ = summarize_codex_events(events)
        self.assertEqual(classify_error(errors[0]), "model")

    def test_classify(self):
        self.assertEqual(classify_error("You've hit your usage limit. Try again later."), "quota")
        self.assertEqual(classify_error("HTTP 429 Too Many Requests"), "quota")
        self.assertEqual(classify_error("Not logged in. Please log in."), "login")
        self.assertIsNone(classify_error("some other failure"))

    def test_parse_json_loose(self):
        self.assertEqual(parse_json_loose('{"a": 1}'), {"a": 1})
        self.assertEqual(parse_json_loose('설명\n```json\n{"a": 2}\n```'), {"a": 2})
        self.assertEqual(parse_json_loose('앞 {"a": 3} 뒤'), {"a": 3})
        self.assertIsNone(parse_json_loose("json 아님"))
        self.assertIsNone(parse_json_loose("[1, 2]"))


def strict_problems(schema, path="$"):
    """Codex `--output-schema`(엄격 모드) 규칙: 모든 객체가 additionalProperties=false이고 required가 properties와 정확히 같다.
    어기면 진짜 실행이 스키마 오류로 거절된다 (가짜 실행기는 검사하지 않아 화면 확인으로는 못 잡는다)."""
    out = []
    kind = schema.get("type")
    if kind == "object":
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            out.append(f"{path}: additionalProperties가 false가 아님")
        req = set(schema.get("required") or [])
        if req != set(props):
            out.append(f"{path}: required와 properties가 다름 (required에서 빠짐 {sorted(set(props) - req)}, 없는 항목 {sorted(req - set(props))})")
        for key, sub in props.items():
            out += strict_problems(sub, f"{path}.{key}")
    elif kind == "array":
        out += strict_problems(schema.get("items", {}), path + "[]")
    return out


class HostSkills(unittest.TestCase):
    """Codex는 --ignore-user-config여도 이 PC의 개인 스킬을 보여 준다: 직원이 열어 읽은 것은 회사 스킬과 따로 기록한다."""

    def cmd(self, path):
        return {"type": "item.completed", "item": {"type": "command_execution", "command": f"Get-Content -LiteralPath '{path}'"}}

    def test_reads_of_personal_skill_files_are_named(self):
        from studio.runtimes import host_skills_read

        b = chr(92)
        home = "C:" + b + "Users" + b + "bark" + b
        events = [
            self.cmd(home + ".codex" + b + "skills" + b + "coding-standards" + b + "SKILL.md"),
            self.cmd(home + ".codex" + b + "skills" + b + "coding-standards" + b + "SKILL.md"),  # 시작·끝 이벤트가 둘씩 온다
            self.cmd("C:/Users/bark/.codex/skills/.system/imagegen/SKILL.md"),
            self.cmd(home + ".agents" + b + "skills" + b + "Deep-Research" + b + "SKILL.md"),
            self.cmd(home + "ai studio" + b + "skills" + b + "company-skill" + b + "SKILL.md"),  # 회사 스킬 폴더는 개인 스킬이 아니다
            self.cmd(home + ".codex" + b + "skills" + b + "figma" + b + "notes.md"),  # SKILL.md가 아니면 아니다
            {"type": "item.completed", "item": {"type": "agent_message", "text": ".codex/skills/x/SKILL.md 를 읽었어요"}},
        ]
        self.assertEqual(host_skills_read(events), ["coding-standards", "imagegen", "Deep-Research"])
        self.assertEqual(host_skills_read([]), [])
        self.assertEqual(host_skills_read([self.cmd("C:/Users/bark/.cli-jaw/skills/synced/x/memo/SKILL.md")]), [],
                         "cli-jaw 아래 여러 단계 폴더는 이름을 한 칸만 잡으므로 셈하지 않는다")
        self.assertEqual(host_skills_read([self.cmd("C:/Users/bark/.cli-jaw/skills/memo/SKILL.md")]), ["memo"])

    def test_personal_skill_files_are_found_and_blocked(self):
        # CEO 결정 (2026-09-29): 개인 스킬은 직원에게 보이지 않게 끈다 — 코덱스 기본(.system)·플러그인 스킬은 그대로
        import tempfile
        from pathlib import Path
        from unittest import mock

        from studio import runtimes
        from studio.runtimes import CodexRuntime, RunSpec, codex_skill_block_args, host_skill_files

        with tempfile.TemporaryDirectory(prefix="ais-home-") as d:
            home = Path(d)
            for rel in (".codex/skills/tidy/SKILL.md", ".codex/skills/.system/imagegen/SKILL.md", ".codex/skills/nested/deep/SKILL.md",
                        ".codex/skills/tidy/notes.md", ".agents/skills/memo/SKILL.md", ".codex/plugins/cache/x/skills/pdf/SKILL.md"):
                (home / rel).parent.mkdir(parents=True, exist_ok=True)
                (home / rel).write_text("---\nname: x\n---\n", encoding="utf-8")
            found = host_skill_files(home=home, codex_home=home / ".codex")
            names = [p.split("/")[-2] for p in found]
            self.assertEqual(sorted(names), ["deep", "memo", "tidy"])
            self.assertTrue(all(p.startswith(home.resolve().as_posix()) for p in found))
            self.assertEqual(host_skill_files(home=home / "nobody", codex_home=home / "nobody"), [])
            args = codex_skill_block_args(found)
            self.assertEqual(args[0], "-c")
            self.assertTrue(args[1].startswith("skills.config=[{path=") and args[1].count("enabled=false") == 3)
            self.assertEqual(codex_skill_block_args([]), [])
            self.assertLessEqual(len(codex_skill_block_args([f"C:/x/{i:04d}/SKILL.md" for i in range(2000)])[1]), runtimes.BLOCK_ARG_MAX + 20)

            # 실행기가 붙인다 (block_host_skills = false면 안 붙인다)
            seen = {}

            def fake_run(args, **kw):
                seen["args"] = list(args)
                return 0, None, 0.1

            for rcfg, expect in (({}, True), ({"block_host_skills": False}, False)):
                rt = CodexRuntime(rcfg)
                rt.info = {"found": True, "cmd": ["codex"]}
                with mock.patch.object(runtimes, "run_process", fake_run), mock.patch.object(runtimes, "host_skill_files", lambda: found):
                    rt.run(RunSpec(run_id="R1-T1-build1", role="builder", prompt="p", cwd=home, run_dir=home / "run"), lambda: False)
                self.assertEqual(any(a.startswith("skills.config=") for a in seen["args"]), expect, rcfg)


class CliFlags(unittest.TestCase):
    def test_missing_flags_reads_help_text_exactly(self):
        from studio.runtimes import CLAUDE_FLAGS, CODEX_FLAGS, missing_flags

        help_text = """Options:
  -s, --sandbox <MODE>   Sandbox policy
  -C, --cd <DIR>         Working directory
      --skip-git-repo-check
  -c, --config <key=value>
      --output-schema <FILE>"""
        # 짧은 옵션은 다른 옵션의 일부(--sandbox 속 -s 등)로 잘못 찾히지 않는다
        self.assertEqual(missing_flags(help_text, ("-s", "-C", "-c", "--output-schema", "--skip-git-repo-check")), [])
        self.assertEqual(missing_flags("  --sandbox <MODE>", ("-s",)), ["-s"], "--sandbox 안의 -s는 짧은 옵션이 아니다")
        self.assertEqual(missing_flags("  --output-schema-file", ("--output-schema",)), ["--output-schema"], "이름이 긴 다른 옵션의 앞부분은 아니다")
        self.assertEqual(missing_flags(help_text, ("--ignore-user-config", "-o")), ["--ignore-user-config", "-o"])
        # 실행기가 쓰는 옵션 목록은 비어 있지 않고 중복이 없다
        for flags in (CODEX_FLAGS, CLAUDE_FLAGS):
            self.assertTrue(flags)
            self.assertEqual(len(flags), len(set(flags)))


class OutputSchemas(unittest.TestCase):
    def test_every_output_schema_is_strict_mode_safe(self):
        from studio import prompts, skills

        for name, schema in (("PLAN", prompts.PLAN_SCHEMA), ("REVIEW", prompts.REVIEW_SCHEMA), ("TOOL", prompts.TOOL_SCHEMA),
                             ("SKILL", skills.SKILL_SCHEMA)):
            self.assertEqual(strict_problems(schema), [], name)
        # 이 검사가 실제로 잡아내는지: required에서 하나 빠진 스키마는 걸린다
        broken = {"type": "object", "additionalProperties": False, "required": ["a"],
                  "properties": {"a": {"type": "string"}, "skills_used": {"type": "array", "items": {"type": "string"}}}}
        self.assertEqual(len(strict_problems(broken)), 1)

    def test_skill_report_field_is_in_every_json_output(self):
        """기획·리뷰·도구 만들기는 JSON으로만 답하므로 따른 스킬을 skills_used로 알린다."""
        from studio import prompts

        for schema in (prompts.PLAN_SCHEMA, prompts.REVIEW_SCHEMA, prompts.TOOL_SCHEMA):
            self.assertIn("skills_used", schema["properties"])
            self.assertIn("skills_used", schema["required"])


if __name__ == "__main__":
    unittest.main()
