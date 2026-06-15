"""Document parser for various file formats."""

import logging
import re

logger = logging.getLogger(__name__)


def parse_text(content: str) -> str:
    """Parse plain text content."""
    return content.strip()


def parse_markdown(content: str) -> str:
    """Parse markdown content, extracting plain text."""
    # Simple markdown to text conversion
    lines = content.split("\n")
    text_lines = []
    for line in lines:
        # Remove markdown headers
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        # Remove markdown emphasis
        line = line.replace("**", "").replace("*", "").replace("__", "").replace("_", "")
        if line.strip():
            text_lines.append(line.strip())
    return "\n".join(text_lines)


def parse_pdf(content: bytes) -> str:
    """Parse PDF file content, extracting plain text.

    Args:
        content: Raw PDF file bytes.

    Returns:
        Extracted plain text from all pages.

    Raises:
        ValueError: If PDF parsing fails.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ValueError("PyMuPDF 未安装，请运行: pip install PyMuPDF")

    try:
        doc = fitz.open(stream=content, filetype="pdf")
        text_parts = []
        for page in doc:
            page_text = page.get_text()
            if page_text.strip():
                text_parts.append(page_text.strip())
        doc.close()

        if not text_parts:
            logger.warning("PDF file contains no extractable text")
            return ""

        return "\n\n".join(text_parts)
    except Exception as e:
        logger.error(f"PDF parsing failed: {e}")
        raise ValueError(f"PDF 解析失败: {str(e)}")


def parse_docx(content: bytes) -> str:
    """Parse DOCX file content, extracting plain text.

    Args:
        content: Raw DOCX file bytes.

    Returns:
        Extracted plain text from all paragraphs.

    Raises:
        ValueError: If DOCX parsing fails.
    """
    try:
        from docx import Document
    except ImportError:
        raise ValueError("python-docx 未安装，请运行: pip install python-docx")

    try:
        import io
        doc = Document(io.BytesIO(content))
        text_parts = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                text_parts.append(text)

        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    text = cell.text.strip()
                    if text:
                        text_parts.append(text)

        if not text_parts:
            logger.warning("DOCX file contains no extractable text")
            return ""

        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"DOCX parsing failed: {e}")
        raise ValueError(f"DOCX 解析失败: {str(e)}")


def parse_document(content: str, file_type: str) -> str:
    """Parse document content based on file type.

    Args:
        content: Document content as string.
        file_type: File type identifier (e.g., 'txt', 'md', 'pdf', 'docx').

    Returns:
        Parsed plain text content.
    """
    parsers = {
        "text/plain": parse_text,
        "text/markdown": parse_markdown,
        "md": parse_markdown,
        "txt": parse_text,
    }

    parser = parsers.get(file_type, parse_text)
    return parser(content)


def parse_document_binary(content: bytes, file_type: str) -> str:
    """Parse binary document content based on file type.

    Args:
        content: Raw file bytes.
        file_type: File type identifier (e.g., 'pdf', 'docx').

    Returns:
        Extracted plain text content.

    Raises:
        ValueError: If file type is not supported or parsing fails.
    """
    binary_parsers = {
        "pdf": parse_pdf,
        "docx": parse_docx,
    }

    parser = binary_parsers.get(file_type)
    if parser is None:
        raise ValueError(f"不支持的二进制文件格式: {file_type}")

    return parser(content)


# Section keyword mapping: canonical section name -> list of keywords (Chinese + English)
_SECTION_KEYWORDS: dict[str, list[str]] = {
    "basic_info": [
        "基本信息", "个人信息", "个人资料", "联系方式", "个人概况",
        "basic info", "personal info", "contact", "personal details",
    ],
    "summary": [
        "自我评价", "个人总结", "自我介绍", "个人优势", "简介", "概述", "求职意向", "个人简介",
        "summary", "objective", "profile", "about", "self-evaluation",
    ],
    "education": [
        "教育经历", "教育背景", "学历", "教育经验", "求学经历", "学校",
        "education", "academic", "educational background",
    ],
    "skills": [
        "技能", "专业技能", "技术能力", "核心技能", "技能特长", "技术栈",
        "skills", "expertise", "competenc", "proficienc", "technical skills",
    ],
    "experience": [
        "工作经验", "工作经历", "工作背景", "职业经历", "实习经历", "实习经验", "从业经历",
        "experience", "employment", "work history", "professional experience",
    ],
    "projects": [
        "项目经历", "项目经验", "项目背景", "项目成果", "代表项目",
        "projects", "portfolio", "project experience",
    ],
    "other": [
        "证书", "资质认证", "资格证书", "荣誉", "获奖经历", "奖项", "兴趣", "爱好", "语言能力",
        "certif", "award", "honor", "interest", "language", "certification",
    ],
}

# Pre-compile regex patterns for section header detection.
# The pattern supports multiple header formats:
#   - Markdown: ## 工作经验, **技能**, # Education
#   - Chinese brackets: 【工作经历】, 【教育背景】
#   - Bullet symbols: ■ 工作背景, ● Skills, • Projects
#   - Numbered: 1. 工作经验, 2、项目经历, 3) Education
#   - Bare: 工作经验, Education
# Trailing content after the keyword (and optional separator) is captured in group 2.
# For example: "## 工作经验: 5年后端开发" -> group(1)="工作经验", group(2)="5年后端开发"
_SECTION_PATTERNS: dict[str, re.Pattern] = {}
for _section_name, _keywords in _SECTION_KEYWORDS.items():
    # Sort keywords by length descending to match longer phrases first
    sorted_kws = sorted(_keywords, key=len, reverse=True)
    kw_pattern = "|".join(re.escape(kw) for kw in sorted_kws)
    pattern_str = (
        r"^\s*"
        r"(?:"
        r"[#*]{1,6}\s+"           # markdown headers/bold: #, ##, **, etc.
        r"|[■●•\-]\s*"            # single bullet symbols
        r"|\d+[\.\)、]\s*"         # numbered: 1. 1) 1、
        r"|【"                     # Chinese bracket open (closed after keyword)
        r")?"
        r"(" + kw_pattern + r")"
        r"(?:】)?"                 # optional closing Chinese bracket
        r"[\]:：]*"                # optional colon/bracket closers
        r"(?:\s*(.+))?"            # optional trailing content (space-separated or direct)
        r"\s*$"
    )
    _SECTION_PATTERNS[_section_name] = re.compile(pattern_str, re.IGNORECASE)

# Fallback pattern: short lines (< 20 chars) that contain a section keyword
# anywhere in the line, but only if the line doesn't look like a sentence fragment.
# Sentence fragments typically contain common Chinese particles/verbs mid-text.
_SENTENCE_PARTICLES = re.compile(r"[的了着过在是有我你他她它们这那被把让给向从到与和或]")
_FALLBACK_MAX_LEN = 20


def _detect_section(line_stripped: str) -> str | None:
    """Detect if a line is a resume section header.

    Uses anchored regex matching to ensure keywords appear at the start of the line
    (after optional formatting markers), not mid-sentence.

    Args:
        line_stripped: A single stripped line from the resume text.

    Returns:
        The canonical section name if the line is a header, otherwise None.
    """
    if not line_stripped:
        return None

    # Primary check: anchored regex patterns
    for section_name, pattern in _SECTION_PATTERNS.items():
        if pattern.match(line_stripped):
            logger.debug("Section detected (anchored): '%s' -> %s", line_stripped, section_name)
            return section_name

    # Fallback heuristic: short lines containing a keyword
    if len(line_stripped) <= _FALLBACK_MAX_LEN:
        line_lower = line_stripped.lower()
        # Reject lines that look like sentence fragments
        if _SENTENCE_PARTICLES.search(line_stripped):
            return None
        for section_name, keywords in _SECTION_KEYWORDS.items():
            if any(kw in line_lower for kw in keywords):
                logger.debug(
                    "Section detected (fallback): '%s' -> %s", line_stripped, section_name
                )
                return section_name

    return None


def extract_resume_sections(text: str) -> dict:
    """Extract common resume sections from text.

    Parses resume text into structured sections by detecting section headers
    using anchored regex matching and fallback heuristics. Supports both
    Chinese and English headers with various formatting styles.

    Improvements over simple keyword-in-line matching:
    - Keywords must appear at the START of a line (after optional markers like ##, ■, 1.)
    - Expanded keyword lists covering more Chinese resume section title variants
    - Short-line fallback heuristic for non-standard headers
    - Header line content after the marker is preserved as section content
    - Logging for section detection decisions

    Args:
        text: Full resume text.

    Returns:
        Dict with keys: basic_info, summary, education, skills, experience, projects, other.
    """
    sections = {
        "basic_info": "",
        "summary": "",
        "education": "",
        "skills": "",
        "experience": "",
        "projects": "",
        "other": "",
    }

    lines = text.split("\n")
    current_section = "other"

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        detected = _detect_section(line_stripped)
        if detected is not None:
            logger.info("Resume section switch: '%s' -> %s", line_stripped, detected)
            current_section = detected
            # Preserve any content on the same line after the header keyword.
            # For example, "## 工作经验: 5年后端开发" should keep "5年后端开发".
            # The regex captures trailing content in group 2.
            pattern = _SECTION_PATTERNS.get(detected)
            if pattern:
                m = pattern.match(line_stripped)
                if m and m.group(2):
                    remainder = m.group(2).strip()
                    # Strip leading colons/separators that may remain
                    remainder = remainder.lstrip(":：-— ").strip()
                    if remainder:
                        sections[current_section] += remainder + "\n"
        else:
            sections[current_section] += line_stripped + "\n"

    return sections


async def ai_extract_resume_sections(text: str) -> dict:
    """Use LLM to extract resume sections intelligently.

    Args:
        text: Full resume text.

    Returns:
        Dict with sections: basic_info, summary, experience, education, skills, projects, other.
    """
    import json as json_module

    from app.llm.client import get_llm_router

    router = get_llm_router()

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个专业的简历分析师。请从简历文本中提取以下段落：\n\n"
                "1. basic_info - 基本信息（姓名、联系方式、所在城市等）\n"
                "2. summary - 个人简介/自我评价\n"
                "3. education - 教育经历（学校、专业、学位、时间）\n"
                "4. skills - 专业技能（技术栈、工具、方法论）\n"
                "5. experience - 工作经验（公司、职位、职责、成就）\n"
                "6. projects - 项目经历（项目名称、职责、成果）\n"
                "7. other - 其他信息（证书、获奖、语言能力等）\n\n"
                '以 JSON 格式返回，每个字段的值是提取的文本内容。如果某个段落没有内容，返回空字符串。'
            ),
        },
        {
            "role": "user",
            "content": f"请分析以下简历：\n\n{text}",
        },
    ]

    try:
        response = await router.generate_with_fallback(
            messages,
            use_light=True,
            response_format={"type": "json_object"},
        )
        result = json_module.loads(response)

        # Ensure all fields are strings
        sections = {
            "basic_info": str(result.get("basic_info", "")),
            "summary": str(result.get("summary", "")),
            "education": str(result.get("education", "")),
            "skills": str(result.get("skills", "")),
            "experience": str(result.get("experience", "")),
            "projects": str(result.get("projects", "")),
            "other": str(result.get("other", "")),
        }
        return sections
    except Exception as e:
        logger.error(f"AI resume extraction failed: {e}")
        # Fallback to fixed parsing
        return extract_resume_sections(text)
