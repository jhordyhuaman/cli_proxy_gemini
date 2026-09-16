"""Herramientas del agente: contrato, implementaciones y registro."""

from .base import Tool, ToolContext, ToolPathError, ToolResult, resolve_read_path, resolve_write_path
from .bash import BashTool
from .edit import EditTool
from .glob import GlobTool
from .grep import GrepTool
from .read_file import ReadFileTool
from .registry import ToolCall, ToolRegistry, default_registry
from .write_file import WriteFileTool

__all__ = [
    "BashTool",
    "EditTool",
    "GlobTool",
    "GrepTool",
    "ReadFileTool",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolPathError",
    "ToolRegistry",
    "ToolResult",
    "WriteFileTool",
    "default_registry",
    "resolve_read_path",
    "resolve_write_path",
]
