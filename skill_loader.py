import re
from pathlib import Path

import yaml
WORKPATH = Path.cwd()
SKILLS_DIR = WORKPATH / "skills"

class SkillLoader:
    def __init__(self, skills_path: Path):
        self.skills_path = skills_path
        self.skills = {}
        self._load_all()
    def _load_all(self):
        if not self.skills_path.exists():
            return
        for skill in sorted(self.skills_path.rglob("SKILL.md")):
            text = skill.read_text(encoding="utf-8")
            meta, body = self._parse_meta_body(text)
            name = meta.get("name", skill.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(skill)}

    def _parse_meta_body(self, text: str) -> tuple:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        try:
            # yaml.safe_load将元数据解析成字典
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        if not self.skills:
            return str("没有skills可用")
        lines = []
        for name, skill in self.skills.items():
            des = skill["meta"].get("description", "No descriptions")
            tag = skill["meta"].get("tags", "")
            line = f"  -{name} : {des}"
            if tag:
                line += f" [{tag}]"
            lines.append(line)
        return "\n".join(lines)

    def get_content(self, name) -> str:
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"

SKILLSLOADER = SkillLoader(SKILLS_DIR)