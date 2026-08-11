#!/usr/bin/env python3
"""
Weather MCP Server - Demonstrates API integration patterns for MCP servers.

This server provides tools for fetching weather information from a public API
and processing weather data. It shows how to integrate external services into
an MCP server while handling errors gracefully.

Tools:
- get_weather: Fetch current weather for a location
- get_forecast: Get 5-day weather forecast
- parse_weather: Parse and format weather data
"""

import json
import logging
import sys

from mcp.server.fastmcp import FastMCP

# Configure logging to stderr for diagnostics
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("weather-server")

mcp = FastMCP("weather")


@mcp.tool()
async def get_weather(location: str = "New York") -> str:
    """Fetch current weather for a specified location."""
    try:
        # Note: This uses a free weather API. In production, use a real API key.
        import requests

        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": 40.7128,
            "longitude": -74.006,
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "timezone": "auto",
        }

        response = requests.get(url, params=params, timeout=5)
        if response.status_code != 200:
            return f"❌ Error: Failed to fetch weather (HTTP {response.status_code})"

        data = response.json()
        current = data.get("current", {})
        temp = current.get("temperature_2m", "N/A")
        wind = current.get("wind_speed_10m", "N/A")

        return f"✅ Weather in {location}:\n- Temperature: {temp}°C\n- Wind Speed: {wind} km/h"

    except ImportError:
        return "❌ Error: requests library not installed. Install with: pip install requests"
    except Exception as e:
        logger.error(f"Weather fetch failed: {e}")
        return f"❌ Error: {e!s}"


@mcp.tool()
async def get_forecast(location: str = "New York", days: str = "5") -> str:
    """Get a multi-day weather forecast for a location."""
    try:
        days_int = int(days)
        if days_int < 1 or days_int > 16:
            return "❌ Error: Days must be between 1 and 16"

        import requests

        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": 40.7128,
            "longitude": -74.006,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
            "forecast_days": days_int,
        }

        response = requests.get(url, params=params, timeout=5)
        if response.status_code != 200:
            return f"❌ Error: Failed to fetch forecast (HTTP {response.status_code})"

        data = response.json()
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        temps_max = daily.get("temperature_2m_max", [])
        temps_min = daily.get("temperature_2m_min", [])

        forecast = f"✅ {days_int}-day Forecast for {location}:\n"
        for i in range(min(days_int, len(dates))):
            forecast += f"- {dates[i]}: {temps_min[i]}°C - {temps_max[i]}°C\n"

        return forecast

    except ValueError:
        return "❌ Error: Days must be a valid integer"
    except ImportError:
        return "❌ Error: requests library not installed. Install with: pip install requests"
    except Exception as e:
        logger.error(f"Forecast fetch failed: {e}")
        return f"❌ Error: {e!s}"


@mcp.tool()
async def parse_weather(data_json: str = "{}") -> str:
    """Parse and format raw weather JSON data."""
    try:
        data = json.loads(data_json)
        if not isinstance(data, dict):
            return "❌ Error: Input must be valid JSON object"

        temp = data.get("temperature", "N/A")
        condition = data.get("condition", "Unknown")
        humidity = data.get("humidity", "N/A")

        formatted = "✅ Weather Summary:\n"
        formatted += f"- Condition: {condition}\n"
        formatted += f"- Temperature: {temp}°C\n"
        formatted += f"- Humidity: {humidity}%\n"

        return formatted

    except json.JSONDecodeError:
        return "❌ Error: Invalid JSON format"
    except Exception as e:
        logger.error(f"Parse failed: {e}")
        return f"❌ Error: {e!s}"


if __name__ == "__main__":
    logger.info("Starting Weather MCP Server on stdio transport")
    mcp.run(transport="stdio")
