#!/usr/bin/env python3
"""
Dice Roller MCP Server - Example MCP implementation for FusionAL

Provides comprehensive dice rolling functionality for tabletop games (D&D, Pathfinder, etc.)
Demonstrates proper MCP patterns: single-line docstrings, error handling, logging
"""

import logging
import random
import sys

from mcp.server.fastmcp import FastMCP

# Configure logging to stderr (required for MCP servers)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger("dice-server")

# Initialize MCP server
mcp = FastMCP("dice")


# === UTILITY FUNCTIONS ===
def parse_dice_notation(notation):
    """Parse dice notation like 2d6+3 into components."""
    try:
        modifier = 0
        if '+' in notation:
            parts = notation.split('+')
            notation = parts[0]
            modifier = int(parts[1])
        elif '-' in notation:
            parts = notation.split('-')
            notation = parts[0]
            modifier = -int(parts[1])
        
        if 'd' in notation.lower():
            parts = notation.lower().split('d')
            num_dice = int(parts[0]) if parts[0] else 1
            sides = int(parts[1])
            return num_dice, sides, modifier
        else:
            return 1, int(notation), modifier
    except:
        return None, None, None


# === MCP TOOLS ===

@mcp.tool()
async def roll_dice(notation: str = "1d20") -> str:
    """Roll dice using standard notation like 1d20, 2d6+3, 3d8-2."""
    logger.info(f"Rolling dice: {notation}")
    
    try:
        if not notation.strip():
            notation = "1d20"
        
        num_dice, sides, modifier = parse_dice_notation(notation)
        if num_dice is None:
            return f"❌ Error: Invalid dice notation '{notation}'. Use format like '2d6' or '1d20+5'"
        
        if num_dice < 1 or num_dice > 100:
            return "❌ Error: Number of dice must be between 1 and 100"
        if sides < 2 or sides > 1000:
            return "❌ Error: Dice sides must be between 2 and 1000"
        
        rolls = [random.randint(1, sides) for _ in range(num_dice)]
        total = sum(rolls) + modifier
        
        rolls_str = " + ".join(str(r) for r in rolls)
        if modifier > 0:
            result = f"🎲 Rolled {notation}: {rolls_str} + {modifier} = **{total}**"
        elif modifier < 0:
            result = f"🎲 Rolled {notation}: {rolls_str} - {abs(modifier)} = **{total}**"
        else:
            result = f"🎲 Rolled {notation}: {rolls_str} = **{total}**"
        
        return result
    except Exception as e:
        logger.error(f"Error: {e}")
        return f"❌ Error: {e!s}"


@mcp.tool()
async def roll_stats() -> str:
    """Roll D&D ability scores using 4d6 drop lowest method."""
    logger.info("Rolling D&D stats")
    
    try:
        stats = []
        details = []
        
        for i in range(6):
            rolls = sorted([random.randint(1, 6) for _ in range(4)], reverse=True)
            kept = rolls[:3]
            dropped = rolls[3]
            stat_total = sum(kept)
            stats.append(stat_total)
            details.append(f"  {i+1}. Rolled: {rolls} → Kept {kept} (dropped {dropped}) = **{stat_total}**")
        
        stats_sorted = sorted(stats, reverse=True)
        total = sum(stats)
        
        return f"""⚔️ **D&D Ability Scores** (4d6 drop lowest):

{chr(10).join(details)}

**Final Stats:** {', '.join(str(s) for s in stats)}
**Sorted:** {', '.join(str(s) for s in stats_sorted)}
**Total:** {total}"""
    except Exception as e:
        logger.error(f"Error: {e}")
        return f"❌ Error: {e!s}"


@mcp.tool()
async def flip_coin(count: str = "1") -> str:
    """Flip one or more coins (heads or tails)."""
    logger.info(f"Flipping {count} coin(s)")
    
    try:
        num_coins = int(count) if count.strip() else 1
        if num_coins < 1 or num_coins > 1000:
            return "❌ Error: Must flip between 1 and 1000 coins"
        
        results = []
        for _ in range(num_coins):
            results.append("Heads" if random.randint(0, 1) == 1 else "Tails")
        
        if num_coins == 1:
            return f"🪙 Coin flip: **{results[0]}**"
        else:
            heads = results.count("Heads")
            tails = results.count("Tails")
            return f"""🪙 Flipped {num_coins} coins:
- Heads: {heads} ({heads/num_coins*100:.1f}%)
- Tails: {tails} ({tails/num_coins*100:.1f}%)"""
    except ValueError:
        return f"❌ Error: Invalid count: {count}"
    except Exception as e:
        logger.error(f"Error: {e}")
        return f"❌ Error: {e!s}"


@mcp.tool()
async def roll_check(dc: str = "15", modifier: str = "0", skill: str = "Check") -> str:
    """Make a skill check against a DC (Difficulty Class)."""
    logger.info(f"Rolling skill check DC {dc} with modifier {modifier}")
    
    try:
        difficulty_class = int(dc) if dc.strip() else 15
        mod = int(modifier) if modifier.strip() else 0
        skill_name = skill.strip() if skill.strip() else "Check"
        
        roll = random.randint(1, 20)
        total = roll + mod
        success = total >= difficulty_class
        
        result = f"🎲 **{skill_name} (DC {difficulty_class}):**\n  Rolled: {roll}"
        
        if mod != 0:
            result += f" {'+' if mod >= 0 else '-'} {abs(mod)} = **{total}**"
        else:
            result += f" = **{total}**"
        
        if roll == 20:
            result += "\n  🌟 **NATURAL 20! CRITICAL SUCCESS!**"
        elif roll == 1:
            result += "\n  💀 **NATURAL 1! CRITICAL FAILURE!**"
        elif success:
            margin = total - difficulty_class
            result += f"\n  ✅ **SUCCESS!** (by {margin} point{'s' if margin != 1 else ''})"
        else:
            margin = difficulty_class - total
            result += f"\n  ❌ **FAILURE** (missed by {margin})"
        
        return result
    except ValueError:
        return f"❌ Error: Invalid input - DC: {dc}, modifier: {modifier}"
    except Exception as e:
        logger.error(f"Error: {e}")
        return f"❌ Error: {e!s}"


# === SERVER STARTUP ===
if __name__ == "__main__":
    logger.info("Starting Dice Roller MCP server...")
    
    try:
        mcp.run(transport='stdio')
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)
