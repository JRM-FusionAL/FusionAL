#!/usr/bin/env python3
"""
File Utilities MCP Server - Demonstrates file operation patterns for MCP servers.

This server provides tools for common file operations like counting lines,
getting file info, and text search. It shows how to build MCP servers that
safely interact with the filesystem with proper error handling.

Tools:
- count_lines: Count lines in a file
- get_file_info: Get file metadata (size, modification date, etc.)
- search_text: Search for text patterns in a file
- list_files: List files in a directory with filtering
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Configure logging to stderr for diagnostics
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("file-utils-server")

mcp = FastMCP("file-utils")


@mcp.tool()
async def count_lines(filepath: str = "README.md") -> str:
    """Count total lines in a file."""
    try:
        path = Path(filepath)
        if not path.exists():
            return f"❌ Error: File not found: {filepath}"

        if not path.is_file():
            return f"❌ Error: Not a file: {filepath}"

        with open(path, "r", encoding="utf-8") as f:
            lines = len(f.readlines())

        return f"✅ File: {filepath}\n- Total lines: {lines}"

    except PermissionError:
        return f"❌ Error: Permission denied reading: {filepath}"
    except UnicodeDecodeError:
        return f"❌ Error: File is not valid UTF-8 text: {filepath}"
    except Exception as e:
        logger.error(f"Count lines failed: {e}")
        return f"❌ Error: {e!s}"


@mcp.tool()
async def get_file_info(filepath: str = "README.md") -> str:
    """Get file metadata including size, modification time, and permissions."""
    try:
        path = Path(filepath)
        if not path.exists():
            return f"❌ Error: File not found: {filepath}"

        stat = path.stat()
        size_kb = stat.st_size / 1024
        mod_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        is_readable = os.access(path, os.R_OK)
        is_writable = os.access(path, os.W_OK)

        info = f"✅ File Info: {filepath}\n"
        info += f"- Size: {size_kb:.2f} KB\n"
        info += f"- Modified: {mod_time}\n"
        info += f"- Type: {'Directory' if path.is_dir() else 'File'}\n"
        info += f"- Readable: {is_readable}\n"
        info += f"- Writable: {is_writable}\n"

        return info

    except PermissionError:
        return f"❌ Error: Permission denied accessing: {filepath}"
    except Exception as e:
        logger.error(f"Get file info failed: {e}")
        return f"❌ Error: {e!s}"


@mcp.tool()
async def search_text(filepath: str = "README.md", pattern: str = "TODO") -> str:
    """Search for a text pattern in a file (case-insensitive)."""
    try:
        path = Path(filepath)
        if not path.exists():
            return f"❌ Error: File not found: {filepath}"

        if not path.is_file():
            return f"❌ Error: Not a file: {filepath}"

        matches = []
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if pattern.lower() in line.lower():
                    matches.append((line_num, line.strip()))

        if not matches:
            return f"ℹ️  No matches found for '{pattern}' in {filepath}"

        result = f"✅ Found {len(matches)} match(es) for '{pattern}':\n"
        for line_num, line_text in matches[:10]:  # Show first 10 matches
            result += f"- Line {line_num}: {line_text[:60]}...\n"

        if len(matches) > 10:
            result += f"... and {len(matches) - 10} more matches"

        return result

    except PermissionError:
        return f"❌ Error: Permission denied reading: {filepath}"
    except UnicodeDecodeError:
        return f"❌ Error: File is not valid UTF-8 text: {filepath}"
    except Exception as e:
        logger.error(f"Search text failed: {e}")
        return f"❌ Error: {e!s}"


@mcp.tool()
async def list_files(directory: str = ".", extension: str = "*") -> str:
    """List files in a directory, optionally filtered by extension."""
    try:
        path = Path(directory)
        if not path.exists():
            return f"❌ Error: Directory not found: {directory}"

        if not path.is_dir():
            return f"❌ Error: Not a directory: {directory}"

        # List files with optional extension filter
        if extension == "*":
            files = [f for f in path.iterdir() if f.is_file()]
        else:
            # Ensure extension starts with a dot
            ext = extension if extension.startswith(".") else f".{extension}"
            files = [f for f in path.iterdir() if f.is_file() and f.suffix == ext]

        if not files:
            return f"ℹ️  No files found in {directory}" + (
                f" with extension {extension}" if extension != "*" else ""
            )

        result = f"✅ Files in {directory}:\n"
        for f in sorted(files)[:20]:  # Show first 20 files
            size_kb = f.stat().st_size / 1024
            result += f"- {f.name} ({size_kb:.2f} KB)\n"

        if len(files) > 20:
            result += f"... and {len(files) - 20} more files"

        return result

    except PermissionError:
        return f"❌ Error: Permission denied accessing: {directory}"
    except Exception as e:
        logger.error(f"List files failed: {e}")
        return f"❌ Error: {e!s}"


if __name__ == "__main__":
    logger.info("Starting File Utils MCP Server on stdio transport")
    mcp.run(transport="stdio")
