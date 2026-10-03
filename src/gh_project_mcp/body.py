"""The issue body codec: fields in, Markdown out, and back, without disturbing what a person wrote (ADR-0002).

A body is split into segments: the text before the first `## ` heading, then one segment per section. Every segment
keeps its original text. Reading never normalises, and setting a field re-renders that field's segment only, so a
section the server does not recognise, free text someone added, and even a known section someone reformatted all
survive until that one field is edited.
"""

import re
from dataclasses import dataclass
from typing import Any

from .kinds import ATTR, CHECKLIST, LEAD, LIST, REFS, FieldSpec, field_specs

_HEADING = re.compile(r"^## +(\S.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")
_CHECKBOX = re.compile(r"^\[([ xX])\]\s+(.*)$", re.DOTALL)
_ATTR = re.compile(r"\*\*([A-Za-z][A-Za-z -]*):\*\*\s*([^·\n]*)")
_ESCAPED = re.compile(r"^\\+## ")
_ESCAPABLE = re.compile(r"^\\*## ")
_ISSUE_REF = re.compile(r"#(\d+)")
ATTR_SEPARATOR = " · "


_FENCE = re.compile(r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?)?(?:```|~~~)")


def _is_fence(line: str) -> bool:
    """Whether a line opens or closes a fenced code block, including one that starts a list item."""
    return bool(_FENCE.match(line))


def _close_fences(text: str) -> str:
    """An unclosed fence would swallow every section after it."""
    return text + "\n```" if sum(1 for line in text.split("\n") if _is_fence(line)) % 2 else text


def _normalise_heading(heading: str) -> str:
    return " ".join(heading.lower().rstrip(":").split())


def _map_outside_fences(text: str, fn) -> str:
    """Apply fn to each line that is not inside a fenced code block."""
    out, in_fence = [], False
    for line in text.split("\n"):
        if _is_fence(line):
            in_fence = not in_fence
            out.append(line)
        else:
            out.append(line if in_fence else fn(line))
    return "\n".join(out)


def _escape(text: str) -> str:
    """Keep a line of prose that starts with `## ` from being read as a section heading."""
    return _map_outside_fences(text, lambda line: "\\" + line if _ESCAPABLE.match(line) else line)


def _unescape(text: str) -> str:
    return _map_outside_fences(text, lambda line: line[1:] if _ESCAPED.match(line) else line)


def clean_text(value: Any) -> str:
    """A text value as it will be stored: trimmed, Unix line endings, code fences closed."""
    return _close_fences(str(value).replace("\r\n", "\n").replace("\r", "\n").strip())


def _fence_in_item(line: str) -> bool:
    return any(_is_fence(prefix + line) for prefix in ("", "- ", "- [ ] "))


def clean_item(value: Any) -> str:
    """A list item as it will be stored: one paragraph, no blank or indented lines.

    A code fence inside a bullet would open a block the codec cannot see the end of, so its marker is escaped.
    """
    lines = [line.strip() for line in str(value).replace("\r", "\n").split("\n")]
    return "\n".join("\\" + line if _fence_in_item(line) else line for line in lines if line)


def _lines(text: str) -> list[str]:
    """Lines with their endings, split at newlines only (str.splitlines also splits at form feeds and the like)."""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _clean_ref(value: Any) -> int:
    match = re.fullmatch(r"#?(\d+)", str(value).strip())
    if not match:
        raise ValueError(f"{value!r} is not an issue number")
    return int(match.group(1))


@dataclass
class _Section:
    heading_line: str  # with its line ending
    content: str
    spec: FieldSpec | None
    written: bool = False  # the server wrote this section in this edit

    @property
    def text(self) -> str:
        return self.heading_line + self.content


def _parse_items(content: str) -> list[str]:
    """The bullets of a section. A line that is neither a bullet nor indented continues the item before it."""
    items: list[list[str]] = []
    for raw in content.replace("\r\n", "\n").split("\n"):
        if not raw.strip():
            continue
        bullet = _BULLET.match(raw)
        if bullet:
            items.append([bullet.group(1).strip()])
        elif items:
            items[-1].append(raw.strip())
        else:
            items.append([raw.strip()])
    return ["\n".join(lines) for lines in items]


def _render_items(items: list[str], prefix: str = "") -> str:
    return "\n".join("- " + prefix + item.replace("\n", "\n  ") for item in items)


class Document:
    """One issue body (or milestone description), read as a record of a kind."""

    def __init__(self, text: str | None, kind: str):
        self.kind = kind
        self._original = text or ""
        self._dirty = False
        self._specs = {spec.name: spec for spec in field_specs(kind)}
        by_heading = {_normalise_heading(spec.heading): spec for spec in field_specs(kind) if spec.shape != ATTR}
        self._order = [spec.name for spec in field_specs(kind)]

        self._preamble = ""
        self._sections: list[_Section] = []
        seen: set[str] = set()
        in_fence = False
        for line in _lines(self._original):
            heading = None if in_fence else _HEADING.match(line.rstrip("\r\n"))
            if _is_fence(line):
                in_fence = not in_fence
            if heading:
                spec = by_heading.get(_normalise_heading(heading.group(1)))
                if spec is not None and (spec.name in seen or spec.shape in (ATTR, LEAD)):
                    spec = None  # a second section of the same name is somebody's text, not the field
                if spec is not None:
                    seen.add(spec.name)
                self._sections.append(_Section(line, "", spec))
            elif self._sections:
                self._sections[-1].content += line
            else:
                self._preamble += line

    # -- reading ------------------------------------------------------------------------------------------------

    def _section(self, name: str) -> _Section | None:
        return next((s for s in self._sections if s.spec is not None and s.spec.name == name), None)

    def _attr_line(self) -> tuple[int, list[tuple[str, str]]] | None:
        """Where the attribute line is in the preamble, and the label/value pairs on it."""
        labels = {spec.heading.lower() for spec in self._specs.values() if spec.shape == ATTR}
        for index, line in enumerate(_lines(self._preamble)):
            pairs = [(label.strip(), value.strip()) for label, value in _ATTR.findall(line)]
            if any(label.lower() in labels for label, _ in pairs):
                return index, pairs
        return None

    def _attrs(self) -> dict[str, str]:
        found = self._attr_line()
        if not found:
            return {}
        by_label = {spec.heading.lower(): spec.name for spec in self._specs.values() if spec.shape == ATTR}
        return {by_label[label.lower()]: value for label, value in found[1] if label.lower() in by_label and value}

    def _lead(self) -> str:
        return _unescape(clean_text(self._preamble))

    def get(self, name: str) -> Any:
        """A field's value, or None when the body does not hold it."""
        spec = self._specs[name]
        if spec.shape == ATTR:
            return self._attrs().get(name)
        if spec.shape == LEAD:
            return self._lead() or None
        section = self._section(name)
        if section is None:
            return None
        if spec.shape == REFS:
            return [int(n) for n in _ISSUE_REF.findall(section.content)] or None
        if spec.shape == LIST:
            return _parse_items(section.content) or None
        if spec.shape == CHECKLIST:
            return [text for text, _ in self.checklist(name)] or None
        return _unescape(clean_text(section.content)) or None

    def checklist(self, name: str) -> list[tuple[str, bool]]:
        """A checklist field's items with whether each is ticked."""
        section = self._section(name)
        items = []
        for item in _parse_items(section.content) if section else []:
            box = _CHECKBOX.match(item)
            items.append((box.group(2).strip(), box.group(1) != " ") if box else (item, False))
        return items

    def fields(self) -> dict[str, Any]:
        """Every field the body holds, in the kind's order."""
        values = {name: self.get(name) for name in self._order}
        return {name: value for name, value in values.items() if value is not None}

    @property
    def recognised(self) -> bool:
        """Whether anything in the body reads as a field of this kind."""
        return bool(self.fields())

    @property
    def other_sections(self) -> list[str]:
        """Headings of the sections that are not fields of this kind."""
        return [_HEADING.match(s.heading_line.rstrip("\r\n")).group(1) for s in self._sections if s.spec is None]

    # -- writing ------------------------------------------------------------------------------------------------

    def set(self, name: str, value: Any) -> None:
        """Set one field; None, an empty string or an empty list removes it. Nothing else changes."""
        spec = self._specs[name]
        if spec.choices and value not in (None, "") and value not in spec.choices:
            raise ValueError(f"{name} must be one of {', '.join(spec.choices)}")
        if spec.shape == ATTR:
            # One line, and never the separator that divides one attribute from the next.
            self._set_attr(spec, " ".join(str(value).replace("·", "-").split()) if value else None)
        elif spec.shape == LEAD:
            text = _escape(clean_text(value)) if value else ""
            self._preamble = text + "\n\n" if text and self._sections else text
        else:
            self._set_section(spec, self._render_value(spec, value))
        self._dirty = True

    def _render_value(self, spec: FieldSpec, value: Any) -> str:
        if not value:
            return ""
        if spec.shape == REFS:
            return "\n".join(f"- #{n}" for n in dict.fromkeys(_clean_ref(v) for v in value))
        if spec.shape in (LIST, CHECKLIST):
            items = [item for item in (clean_item(v) for v in value) if item]
            if spec.shape == LIST:
                return _render_items(items)
            ticked = {text for text, done in self.checklist(spec.name) if done}
            return "\n".join(
                "- " + ("[x] " if item in ticked else "[ ] ") + item.replace("\n", "\n  ") for item in items
            )
        return _escape(clean_text(value))

    def _set_attr(self, spec: FieldSpec, value: str | None) -> None:
        found = self._attr_line()
        attr_specs = [s for s in self._specs.values() if s.shape == ATTR]
        known = {s.heading.lower() for s in attr_specs}
        current = self._attrs()
        if value:
            current[spec.name] = value
        else:
            current.pop(spec.name, None)
        pairs = [(s.heading, current[s.name]) for s in attr_specs if s.name in current]
        if found:
            pairs += [(label, v) for label, v in found[1] if label.lower() not in known]
        line = ATTR_SEPARATOR.join(f"**{label}:** {v}" for label, v in pairs)

        lines = _lines(self._preamble)
        if found:
            ending = lines[found[0]][len(lines[found[0]].rstrip("\r\n")) :]
            lines[found[0] : found[0] + 1] = [line + ending] if line else []
            self._preamble = "".join(lines)
        elif line:
            rest = self._preamble.lstrip("\r\n")
            self._preamble = line + "\n\n" + rest if rest or self._sections else line
        if not self._preamble.strip():
            self._preamble = ""

    def _set_section(self, spec: FieldSpec, rendered: str) -> None:
        section = self._section(spec.name)
        if not rendered:
            if section is not None:
                self._sections.remove(section)
            return
        if section is not None:
            section.content, section.written = f"\n{rendered}\n\n", True
            return
        position = self._order.index(spec.name)
        index = len(self._sections)
        earlier = [i for i, s in enumerate(self._sections) if s.spec and self._order.index(s.spec.name) < position]
        later = [i for i, s in enumerate(self._sections) if s.spec and self._order.index(s.spec.name) > position]
        if earlier:
            index = earlier[-1] + 1
        elif later:
            index = later[0]
        self._sections.insert(index, _Section(f"## {spec.heading}\n", f"\n{rendered}\n\n", spec, written=True))

    def render(self) -> str:
        """The body. Unedited, it is exactly the text that was read."""
        if not self._dirty:
            return self._original
        out = self._preamble
        for section in self._sections:
            if section.written and out and not out.endswith("\n\n"):
                # A section the server wrote needs a blank line above its heading; text it did not write is left
                # exactly as it was, spacing included.
                out += "\n" if out.endswith("\n") else "\n\n"
            out += section.text
        return out.rstrip()


def new_body(kind: str, fields: dict[str, Any]) -> str:
    """The body of a new record holding these fields."""
    return edit_body(None, kind, fields)


def edit_body(text: str | None, kind: str, changes: dict[str, Any]) -> str:
    """A body with the named fields set and everything else as it was."""
    document = Document(text, kind)
    for name, value in changes.items():
        document.set(name, value)
    return document.render()
